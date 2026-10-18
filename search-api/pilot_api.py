"""Read-only API over the document pilot's stores (pilot/ in this repo).

Separate from the app: it reads only the pilot namespace, the `pilot_*` Qdrant collections and
the `:Pilot` nodes in Neo4j, and touches nothing the search above uses.

  PILOT_QDRANT_URL          default QDRANT_URL or http://localhost:6343
  PILOT_QDRANT_API_KEY      default QDRANT_API_KEY
  PILOT_COLLECTION_PREFIX   default pilot_
  PILOT_NEO4J_LABEL_PREFIX  default Pilot (same Neo4j as graph_api: NEO4J_URL/USER/PASSWORD)
  PILOT_FILES_DIR           <pilot run dir>/files, to serve the stored documents (optional)
  VECTORIZER_URL            BGE-M3, for semantic search and /ask
"""
import json
import os
import re
import uuid
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from graph_api import get_driver

router = APIRouter(prefix="/api/pilot", tags=["pilot"])

QDRANT_URL = os.getenv("PILOT_QDRANT_URL", os.getenv("QDRANT_URL", "http://localhost:6343"))
QDRANT_API_KEY = os.getenv("PILOT_QDRANT_API_KEY", os.getenv("QDRANT_API_KEY", ""))
PREFIX = os.getenv("PILOT_COLLECTION_PREFIX", "pilot_")
LABEL = os.getenv("PILOT_NEO4J_LABEL_PREFIX", "Pilot")
FILES_DIR = os.getenv("PILOT_FILES_DIR", "")
VECTORIZER_URL = os.getenv("VECTORIZER_URL", "http://localhost:8089").rstrip("/")

# Same namespace as pilot/placsp_pilot/index.py, so point ids can be computed instead of searched.
NS = uuid.UUID("6f1c3a52-5b0e-4f37-9a1e-7d2b8c4e0a11")
SHARED = ("org:", "jv:", "qualification:")          # nodes that span tenders
CHUNK_RELS = ["HAS_CHUNK", "NEXT", "MENTIONS", "MENTIONED_IN"]
JSON_PROPS = ("detail", "conflicts", "attributes")
HEAVY = {"evidence", "descriptions", "documents", "file_path", "aliases", "text"}
CARD = ["tender_id", "name", "channel", "status", "authority", "value", "published", "counts", "analysable",
        "skip_reason", "contract_type", "procedure", "cpv", "nuts", "description", "companies"]

_client = None


def qdrant():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=30)
    return _client


def coll(short: str) -> str:
    return f"{PREFIX}{short}"


def point_id(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(map(str, parts))))


def embed(text: str) -> list[float]:
    try:
        r = httpx.post(f"{VECTORIZER_URL}/embed", json={"texts": [text], "normalize": True}, timeout=60)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(503, f"vectorizer unavailable: {e}")
    return r.json()["embeddings"][0]


def match(**kw):
    from qdrant_client import models as m
    conds = [m.FieldCondition(key=k, match=m.MatchValue(value=v)) for k, v in kw.items() if v not in (None, "")]
    return m.Filter(must=conds) if conds else None


def scroll_all(short: str, flt=None, fields=True, limit: int = 2000) -> list:
    out, offset = [], None
    while len(out) < limit:
        pts, offset = qdrant().scroll(coll(short), scroll_filter=flt, limit=min(256, limit - len(out)),
                                      offset=offset, with_payload=fields)
        out.extend(pts)
        if offset is None:
            break
    return out


def card(p: dict) -> dict:
    c = {k: p.get(k) for k in CARD}
    c["description"] = (c["description"] or "")[:400]
    c["companies"] = len(p.get("companies") or [])
    return c


def label_of(node) -> str:
    return next((l[len(LABEL):] for l in node.labels if l != LABEL and l.startswith(LABEL)), "Node")


def node_json(node, full: bool = False) -> dict:
    props = dict(node)
    out = {"id": props.pop("id"), "label": label_of(node)}
    if not full:
        props = {k: v for k, v in props.items() if k not in HEAVY}
        if isinstance(props.get("description"), str):
            props["description"] = props["description"][:500]
        if isinstance(props.get("summary"), str):
            props["summary"] = props["summary"][:500]
    props.pop("file_path", None)
    for k in JSON_PROPS:                      # dicts are stored in Neo4j as JSON strings
        if isinstance(props.get(k), str) and props[k][:1] in "{[":
            try:
                props[k] = json.loads(props[k])
            except ValueError:
                pass
    return out | props


# ── endpoints ─────────────────────────────────────────────────────────────

@router.get("/overview")
def overview():
    """What is in the pilot: counts, channels, the companies and authorities seen most often."""
    q = qdrant()
    try:
        counts = {s: q.count(coll(s), exact=True).count for s in ("tenders", "chunks", "entities")}
    except Exception as e:  # collection missing: the pilot has not been indexed here
        raise HTTPException(503, f"pilot collections not available: {e}")
    tenders = [p.payload for p in scroll_all("tenders", fields=["channel", "analysable", "companies", "authority", "counts"])]
    companies, authorities = Counter(), Counter()
    names = {}
    for t in tenders:
        for c in t.get("companies") or []:
            companies[c["id"]] += 1
            names[c["id"]] = c.get("name")
        if t.get("authority"):
            authorities[t["authority"]["id"]] += 1
            names[t["authority"]["id"]] = t["authority"].get("name")
    return {
        "counts": counts | {"documents": sum((t.get("counts") or {}).get("documents", 0) for t in tenders)},
        "channels": dict(Counter(t.get("channel") for t in tenders)),
        "analysable": sum(1 for t in tenders if t.get("analysable")),
        "top_companies": [{"id": k, "name": names[k], "tenders": n} for k, n in companies.most_common(12)],
        "top_authorities": [{"id": k, "name": names[k], "tenders": n} for k, n in authorities.most_common(8)],
    }


@router.get("/tenders")
def tenders(q: str = "", channel: str = "", limit: int = Query(30, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Semantic search over the tenders' descriptions, or the latest first without a query."""
    flt = match(channel=channel)
    if q.strip():
        res = qdrant().query_points(coll("tenders"), query=embed(q.strip()), using="description", query_filter=flt,
                                    limit=limit, offset=offset, with_payload=CARD)
        items = [card(p.payload) | {"score": round(p.score, 3)} for p in res.points]
        return {"mode": "semantic", "results": items, "total": None}
    pts = [p.payload for p in scroll_all("tenders", flt, CARD)]
    pts.sort(key=lambda p: p.get("published") or "", reverse=True)
    return {"mode": "latest", "results": [card(p) for p in pts[offset:offset + limit]], "total": len(pts)}


@router.get("/tenders/{tender_id}")
def tender(tender_id: str):
    """The unified tender object, as indexed: lots, criteria, requirements, results, documents in order."""
    pts = qdrant().retrieve(coll("tenders"), ids=[point_id("tender", tender_id)], with_payload=True)
    if not pts:
        raise HTTPException(404, "tender not in the pilot")
    t = pts[0].payload
    for d in t.get("documents") or []:
        d["stored"] = bool(d.pop("file_path", None))
    return t


@router.get("/tenders/{tender_id}/graph")
def tender_graph(tender_id: str, entities: bool = True):
    """The tender's subgraph without chunks: its own nodes, its documents, and the shared nodes
    (companies, UTEs, qualifications) they touch."""
    if not re.fullmatch(r"[0-9A-Za-z_-]+", tender_id):
        raise HTTPException(400, "bad tender id")
    with get_driver().session() as s:
        core = [r["id"] for r in s.run(
            f"MATCH (n:`{LABEL}`) WHERE n.id = $tid OR n.id CONTAINS $mid RETURN n.id AS id "
            f"UNION MATCH (:`{LABEL}` {{id: $tid}})-[:HAS_DOCUMENT]->(d) RETURN d.id AS id",
            tid=f"tender:{tender_id}", mid=f":{tender_id}:")]
        if not core:
            raise HTTPException(404, "tender not in the graph")
        rows = list(s.run(
            f"MATCH (a:`{LABEL}`)-[r]->(b:`{LABEL}`) WHERE a.id IN $core AND NOT type(r) IN $skip "
            "AND (r.tender IS NULL OR r.tender = $eid) "
            "AND (b.id IN $core OR any(p IN $shared WHERE b.id STARTS WITH p)) RETURN a, r, b "
            f"UNION MATCH (a:`{LABEL}`)-[r]->(b:`{LABEL}`) WHERE b.id IN $core AND NOT type(r) IN $skip "
            "AND (r.tender IS NULL OR r.tender = $eid) AND any(p IN $shared WHERE a.id STARTS WITH p) RETURN a, r, b",
            core=core, skip=CHUNK_RELS, eid=tender_id, shared=list(SHARED)))
        isolated = list(s.run(f"MATCH (n:`{LABEL}`) WHERE n.id IN $core RETURN n", core=core))
    nodes, edges = {}, []
    for row in rows:
        for n in (row["a"], row["b"]):
            nodes.setdefault(n["id"], node_json(n))
        r = row["r"]
        edges.append({"src": row["a"]["id"], "dst": row["b"]["id"], "rel": r.type,
                      **{k: v for k, v in dict(r).items() if k in ("seq", "role", "stage", "tender")}})
    for row in isolated:
        nodes.setdefault(row["n"]["id"], node_json(row["n"]))
    if not entities:  # feed skeleton and documents only
        keep = {k for k, n in nodes.items() if n.get("source") != "document" or n["label"] in ("Document", "Lot")}
        nodes = {k: v for k, v in nodes.items() if k in keep}
        edges = [e for e in edges if e["src"] in keep and e["dst"] in keep]
    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/node")
def node(id: str, chunks: int = Query(6, ge=0, le=30)):
    """One graph node: its properties, its neighbours by relation, the chunks that mention it and
    the tenders it belongs to."""
    with get_driver().session() as s:
        rec = s.run(f"MATCH (n:`{LABEL}` {{id: $id}}) RETURN n", id=id).single()
        if not rec:
            raise HTTPException(404, "node not in the graph")
        rows = list(s.run(
            f"MATCH (n:`{LABEL}` {{id: $id}})-[r]-(m:`{LABEL}`) WHERE NOT type(r) IN $skip "
            "RETURN type(r) AS rel, startNode(r) = n AS out, m LIMIT 300", id=id, skip=CHUNK_RELS))
        prov = list(s.run(
            f"MATCH (n:`{LABEL}` {{id: $id}})-[e:MENTIONED_IN]->(c:`{LABEL}`)<-[:HAS_CHUNK]-(d:`{LABEL}`) "
            f"OPTIONAL MATCH (:`{LABEL}` {{id: 'tender:' + e.tender}})-[h:HAS_DOCUMENT]->(d) "
            "RETURN e, c.qdrant_id AS qid, c.idx AS idx, d.role AS role, d.title AS title, d.sha256 AS sha, h.seq AS seq, "
            "e.tender AS tender ORDER BY e.tender, h.seq, c.idx, e.char_start LIMIT 200", id=id))
    neighbours = defaultdict(list)
    for r in rows:
        neighbours[f"{r['rel']}{'' if r['out'] else ' ←'}"].append(node_json(r["m"]))
    ent = qdrant().retrieve(coll("entities"), ids=[point_id("entity", id)], with_payload=["tender_ids"])
    return {"node": node_json(rec["n"], full=True), "neighbours": dict(neighbours),
            "mentions": _mentions(prov, chunks), "mention_count": len(prov),
            "tender_ids": ent[0].payload.get("tender_ids", []) if ent else []}


def _mentions(rows, limit: int) -> list[dict]:
    """Each mention with the passage around its quote (from the chunk text in Qdrant)."""
    rows = rows[:limit]
    texts = {}
    ids = list({r["qid"] for r in rows if r["qid"]})
    if ids:
        for p in qdrant().retrieve(coll("chunks"), ids=ids, with_payload=["text"]):
            texts[str(p.id)] = p.payload.get("text") or ""
    out = []
    for r in rows:
        e = dict(r["e"])
        text, a, b = texts.get(r["qid"], ""), e.get("char_start"), e.get("char_end")
        if text and a is not None and b is not None:
            before, quote, after = text[max(0, a - 120):a], text[a:b], text[b:b + 240]
        else:
            before, quote, after = "", e.get("quote") or "", ""
        out.append({"tender_id": r["tender"], "doc_seq": r["seq"], "doc_role": r["role"], "doc_title": r["title"],
                    "doc_sha256": r["sha"], "chunk_idx": r["idx"], "page": e.get("page"), "surface": e.get("surface"),
                    "located": e.get("located"), "before": before, "quote": quote, "after": after})
    return out


def chunk_json(p: dict, score: float | None = None) -> dict:
    out = {k: p.get(k) for k in ("tender_id", "doc_sha256", "doc_seq", "doc_role", "doc_title", "doc_url", "chunk_idx",
                                 "page_from", "page_to", "effective_date", "entity_ids")}
    out["text"] = (p.get("text") or "")[:1200]
    if score is not None:
        out["score"] = round(score, 3)
    return out


@router.get("/companies/{org_id:path}")
def company(org_id: str):
    """A company (or authority) across the pilot: the tenders it appears in and its role in each,
    who it competes with, which authorities it works for, and where documents mention it."""
    tenders_ = [p.payload for p in scroll_all("tenders", fields=["tender_id", "name", "channel", "published", "value",
                                                               "status", "authority", "companies"])]
    with get_driver().session() as s:
        rec = s.run(f"MATCH (n:`{LABEL}` {{id: $id}}) RETURN n", id=org_id).single()
    if not rec:
        raise HTTPException(404, "company not in the graph")
    ent = qdrant().retrieve(coll("entities"), ids=[point_id("entity", org_id)], with_payload=["tender_ids"])
    mentioned = set(ent[0].payload.get("tender_ids", [])) if ent else set()
    rows, rivals, authorities = [], Counter(), Counter()
    names = {}
    for t in tenders_:
        roles = set()
        for c in t.get("companies") or []:
            names[c["id"]] = c.get("name")
            if c["id"] == org_id:
                roles |= set(c.get("roles") or [])
        if (t.get("authority") or {}).get("id") == org_id:
            roles.add("authority")
        if not roles and t["tender_id"] not in mentioned:
            continue
        rows.append({k: t.get(k) for k in ("tender_id", "name", "channel", "published", "value", "status")}
                    | {"authority": (t.get("authority") or {}).get("name"), "roles": sorted(roles) or ["mentioned"]})
        if roles & {"bidder", "winner"}:
            for c in t.get("companies") or []:
                if c["id"] != org_id and set(c.get("roles") or []) & {"bidder", "winner"}:
                    rivals[c["id"]] += 1
            if t.get("authority"):
                authorities[(t["authority"]["id"], t["authority"].get("name"))] += 1
    rows.sort(key=lambda r: r.get("published") or "", reverse=True)
    return {"node": node_json(rec["n"], full=True), "tenders": rows,
            "rivals": [{"id": k, "name": names.get(k), "tenders": n} for k, n in rivals.most_common(15)],
            "authorities": [{"id": k[0], "name": k[1], "tenders": n} for k, n in authorities.most_common(15)]}


@router.get("/ask")
def ask(q: str, tender_id: str = "", k: int = Query(8, ge=1, le=30)):
    """GraphRAG retrieval, no generation: the chunks closest to the question, the entities whose
    descriptions are closest, and each entity's neighbourhood in the graph."""
    if not q.strip():
        raise HTTPException(400, "empty question")
    from qdrant_client import models as m
    vec = embed(q.strip())
    chunk_hits = qdrant().query_points(coll("chunks"), query=vec, using="text", query_filter=match(tender_id=tender_id),
                                       limit=k, with_payload=True).points
    ent_filter = m.Filter(must=[m.FieldCondition(key="tender_ids", match=m.MatchAny(any=[tender_id]))]) if tender_id else None
    ent_hits = qdrant().query_points(coll("entities"), query=vec, using="description", query_filter=ent_filter,
                                     limit=6, with_payload=["node_id", "label", "name", "description", "tender_ids"]).points
    ids = [p.payload["node_id"] for p in ent_hits]
    context = defaultdict(list)
    if ids:
        with get_driver().session() as s:
            for r in s.run(f"MATCH (n:`{LABEL}`)-[r]-(m:`{LABEL}`) WHERE n.id IN $ids AND NOT type(r) IN $skip "
                           "WITH n, r, m LIMIT 400 RETURN n.id AS id, type(r) AS rel, startNode(r) = n AS out, m",
                           ids=ids, skip=CHUNK_RELS + ["HAS_DOCUMENT", "NEXT_DOCUMENT"]):
                if len(context[r["id"]]) < 10:
                    context[r["id"]].append({"rel": r["rel"], "out": r["out"], "node": node_json(r["m"])})
    tender_ids = list(dict.fromkeys(p.payload["tender_id"] for p in chunk_hits))
    cards = {}
    if tender_ids:
        for p in qdrant().retrieve(coll("tenders"), ids=[point_id("tender", t) for t in tender_ids], with_payload=CARD):
            cards[p.payload["tender_id"]] = card(p.payload)
    return {
        "chunks": [chunk_json(p.payload, p.score) for p in chunk_hits],
        "entities": [{"id": p.payload["node_id"], "label": p.payload.get("label"), "name": p.payload.get("name"),
                      "description": (p.payload.get("description") or "")[:600], "score": round(p.score, 3),
                      "tender_ids": p.payload.get("tender_ids", []), "context": context.get(p.payload["node_id"], [])}
                     for p in ent_hits],
        "tenders": [cards[t] for t in tender_ids if t in cards],
    }


@router.get("/file/{sha}")
def file(sha: str):
    """A stored document, as downloaded by the pilot (when PILOT_FILES_DIR is mounted)."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(400, "bad sha256")
    if not FILES_DIR:
        raise HTTPException(404, "PILOT_FILES_DIR is not set: use the document's source URL")
    found = sorted(Path(FILES_DIR, sha[:2]).glob(f"{sha}*"))
    if not found:
        raise HTTPException(404, "file not stored")
    return FileResponse(found[0], filename=found[0].name, content_disposition_type="inline")
