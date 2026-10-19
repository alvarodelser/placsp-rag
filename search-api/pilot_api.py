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
import unicodedata
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
MARGIN = 0.08                                      # /search keeps hits within this of the best
CHUNK_RELS = ["HAS_CHUNK", "NEXT", "MENTIONS", "MENTIONED_IN"]
JSON_PROPS = ("detail", "conflicts", "attributes", "formula_model")
HEAVY = {"evidence", "descriptions", "documents", "file_path", "aliases", "text"}
CARD = ["tender_id", "name", "short_title", "channel", "status", "authority", "value", "published", "counts", "analysable",
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
        raise HTTPException(503, f"El vectorizador no responde en {VECTORIZER_URL} ({type(e).__name__}: {e}). "
                                 "Sin él no hay búsqueda por significado ni Preguntar.")
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


@router.get("/health")
def health():
    """What the viewer depends on, each checked on its own, so a broken one is named."""
    out = {"vectorizer_url": VECTORIZER_URL, "qdrant_url": QDRANT_URL, "prefix": PREFIX, "label": LABEL}
    try:
        out["qdrant"] = {s: qdrant().count(coll(s), exact=True).count for s in ("tenders", "chunks", "entities")}
    except Exception as e:  # noqa: BLE001
        out["qdrant"] = f"error: {e}"
    try:
        with get_driver().session() as s:
            out["neo4j"] = s.run(f"MATCH (n:`{LABEL}`) RETURN count(n) AS n").single()["n"]
    except Exception as e:  # noqa: BLE001
        out["neo4j"] = f"error: {getattr(e, 'detail', e)}"
    try:
        out["vectorizer"] = f"ok ({len(embed('prueba'))} dims)"
    except HTTPException as e:
        out["vectorizer"] = f"error: {e.detail}"
    return out


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


@router.get("/documents/{sha}")
def document(sha: str, tender: str, start: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=200)):
    """A document as the pipeline read it: its chunks in order, each with every mention placed in it
    (named by NER or a reference such as "la empresa"), and the entities those mentions point at."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(400, "bad sha256")
    from qdrant_client import models as m
    flt = m.Filter(must=[m.FieldCondition(key="tender_id", match=m.MatchValue(value=tender)),
                         m.FieldCondition(key="doc_sha256", match=m.MatchValue(value=sha)),
                         m.FieldCondition(key="chunk_idx", range=m.Range(gte=start, lt=start + limit))])
    pts = scroll_all("chunks", flt, ["chunk_idx", "page_from", "page_to", "text", "mentions", "ner"], limit=limit)
    chunks = sorted(({k: p.payload.get(k) for k in ("chunk_idx", "page_from", "page_to", "text", "mentions", "ner")} for p in pts),
                    key=lambda c: c["chunk_idx"])
    total = qdrant().count(coll("chunks"), count_filter=m.Filter(must=flt.must[:2]), exact=True).count
    ids = sorted({x["entity_id"] for c in chunks for x in c.get("mentions") or []})
    ents = {}
    if ids:
        for p in qdrant().retrieve(coll("entities"), ids=[point_id("entity", i) for i in ids],
                                   with_payload=["node_id", "label", "name", "subtype"]):
            ents[p.payload["node_id"]] = {k: p.payload.get(k) for k in ("label", "name", "subtype")}
    t = qdrant().retrieve(coll("tenders"), ids=[point_id("tender", tender)], with_payload=["documents", "name"])
    doc = next((d for d in (t[0].payload.get("documents") or []) if d.get("sha256") == sha), {}) if t else {}
    doc = {k: v for k, v in doc.items() if k != "file_path"} | {"stored": bool(doc.get("file_path")), "tender_name": t[0].payload.get("name") if t else None}
    return {"document": doc, "chunks": chunks, "total_chunks": total, "start": start, "entities": ents}


# What a preview shows first: what a bidder reads a document for.
PREVIEW_ORDER = {"AwardCriterion": 0, "Requirement": 1, "TechnicalRequirement": 2, "Guarantee": 3, "Penalty": 4,
                 "TeamProfile": 5, "Deliverable": 6, "Lot": 7, "Organization": 8, "JointVenture": 8}


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


@router.get("/documents/{sha}/preview")
def document_preview(sha: str, tender: str, spans: int = Query(5, ge=0, le=12)):
    """A document at a glance: its place in the tender, its summary and a few passages where the
    pipeline found what matters most in it (criteria and requirements first), the found name marked."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(400, "bad sha256")
    from qdrant_client import models as m
    t = qdrant().retrieve(coll("tenders"), ids=[point_id("tender", tender)], with_payload=["documents"])
    doc = next((d for d in (t[0].payload.get("documents") or []) if d.get("sha256") == sha), None) if t else None
    if doc is None:
        raise HTTPException(404, "document not in this tender")
    keep = ("sha256", "seq", "role", "title", "filename", "summary", "effective_date", "pages", "chars", "entities", "stage")
    out = {"document": {k: doc.get(k) for k in keep}, "spans": [], "mentions": 0}
    if not spans:
        return out
    flt = m.Filter(must=[m.FieldCondition(key="tender_id", match=m.MatchValue(value=tender)),
                         m.FieldCondition(key="doc_sha256", match=m.MatchValue(value=sha))],
                   must_not=[m.IsEmptyCondition(is_empty=m.PayloadField(key="entity_ids"))])
    chunks = scroll_all("chunks", flt, ["chunk_idx", "page_from", "text", "mentions"], limit=400)
    found = [(p.payload, x) for p in chunks for x in p.payload.get("mentions") or []
             if x.get("kind", "ner") == "ner" and x.get("char_start") is not None]
    out["mentions"] = len(found)
    labels = {}
    ids = list({x["entity_id"] for _, x in found})
    for i in range(0, len(ids), 200):
        for p in qdrant().retrieve(coll("entities"), ids=[point_id("entity", e) for e in ids[i:i + 200]],
                                   with_payload=["node_id", "label", "name"]):
            labels[p.payload["node_id"]] = (p.payload.get("label"), p.payload.get("name"))
    found.sort(key=lambda f: (PREVIEW_ORDER.get(labels.get(f[1]["entity_id"], ("",))[0], 9), f[0]["chunk_idx"], f[1]["char_start"]))
    seen = set()
    for c, x in found:
        if x["entity_id"] in seen or x["entity_id"] not in labels:
            continue
        seen.add(x["entity_id"])
        text, a, b = c.get("text") or "", x["char_start"], min(x["char_end"], x["char_start"] + 320)
        ns, ne = x.get("name_start"), x.get("name_end")
        mark = (ns, ne) if ns is not None and ne is not None and a <= ns < ne <= b else (a, b)
        out["spans"].append({"entity_id": x["entity_id"], "label": labels[x["entity_id"]][0], "name": labels[x["entity_id"]][1],
                             "chunk_idx": c["chunk_idx"], "page": x.get("page") or c.get("page_from"),
                             "before": _flat(text[max(0, a - 60):a] + text[a:mark[0]])[-160:], "mark": _flat(text[mark[0]:mark[1]]),
                             "after": _flat(text[mark[1]:b] + text[b:b + 60])[:160]})
        if len(out["spans"]) >= spans:
            break
    return out


@router.get("/graph")
def corpus_graph(documents: bool = False):
    """What the expedientes share: tenders, the authorities that publish them and the companies
    that bid for and win them (roles from the unified tender object); with `documents`, each
    tender's documents too. A tender's own subgraph is at /tenders/{id}/graph."""
    fields = ["tender_id", "name", "short_title", "channel", "status", "value", "authority", "companies", "counts"]
    tenders = [p.payload for p in scroll_all("tenders", fields=fields + (["documents"] if documents else []))]
    nodes, edges = {}, []
    for t in tenders:
        tid = f"tender:{t['tender_id']}"
        nodes[tid] = {"id": tid, "label": "Tender", "name": t.get("name"), "short_title": t.get("short_title"), "channel": t.get("channel"),
                      "status": t.get("status"), "value": t.get("value"), "documents": (t.get("counts") or {}).get("documents")}
        a = t.get("authority")
        if a:
            nodes.setdefault(a["id"], {"id": a["id"], "label": "Organization", "name": a.get("name"), "kinds": ["ContractingAuthority"]})
            edges.append({"src": a["id"], "dst": tid, "rel": "PUBLISHED"})
        for c in t.get("companies") or []:
            n = nodes.setdefault(c["id"], {"id": c["id"], "label": "Organization", "name": c.get("name"), "kinds": ["Company"]})
            if "Company" not in n["kinds"]:
                n["kinds"].append("Company")
            for role in c.get("roles") or []:
                edges.append({"src": c["id"], "dst": tid, "rel": role.upper()})
        for d in t.get("documents") or []:
            if not d.get("sha256"):
                continue
            did = f"doc:{d['sha256']}"
            nodes.setdefault(did, {"id": did, "label": "Document", "role": d.get("role"), "title": d.get("title") or d.get("filename")})
            edges.append({"src": tid, "dst": did, "rel": "HAS_DOCUMENT", "seq": d.get("seq")})
    return {"nodes": list(nodes.values()), "edges": edges}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@router.get("/search")
def search(q: str, scope: str = Query("tenders", pattern="^(all|tenders|companies|authorities)$"),
           k: int = Query(30, ge=1, le=100)):
    """One search for the landing page. Tenders match by their description or by any of their
    chunks (with the best passages shown); companies and authorities by name, then by meaning.
    Only what scores within MARGIN of the best hit is kept, so the list narrows to what fits."""
    q = q.strip()
    if not q:
        raise HTTPException(400, "empty query")
    vec = embed(q)
    out = {"tenders": [], "organizations": []}
    if scope in ("all", "tenders"):
        best, passages = {}, defaultdict(list)
        for p in qdrant().query_points(coll("tenders"), query=vec, using="description", limit=k).points:
            best[p.payload["tender_id"]] = p.score
        for p in qdrant().query_points(coll("chunks"), query=vec, using="text", limit=3 * k, with_payload=True).points:
            t = p.payload["tender_id"]
            best[t] = max(best.get(t, 0), p.score)
            if len(passages[t]) < 2:
                passages[t].append(chunk_json(p.payload, p.score) | {"text": (p.payload.get("text") or "")[:360]})
        top = max(best.values(), default=0)
        ids = sorted((t for t, sc in best.items() if sc >= top - MARGIN), key=lambda t: -best[t])[:k]
        cards = {p.payload["tender_id"]: card(p.payload) for p in
                 qdrant().retrieve(coll("tenders"), ids=[point_id("tender", t) for t in ids], with_payload=CARD)}
        out["tenders"] = [cards[t] | {"score": round(best[t], 3), "passages": passages.get(t, [])} for t in ids if t in cards]
    if scope != "tenders":
        orgs = {}       # the organizations on the landing graph: authorities and companies of the tenders
        for p in scroll_all("tenders", fields=["tender_id", "authority", "companies"]):
            t = p.payload
            if t.get("authority"):
                o = orgs.setdefault(t["authority"]["id"], {"id": t["authority"]["id"], "name": t["authority"].get("name"),
                                                            "kinds": set(), "tender_ids": set()})
                o["kinds"].add("authority"); o["tender_ids"].add(t["tender_id"])
            for c in t.get("companies") or []:
                o = orgs.setdefault(c["id"], {"id": c["id"], "name": c.get("name"), "kinds": set(), "tender_ids": set()})
                o["kinds"].add("company"); o["tender_ids"].add(t["tender_id"])
        want = {"companies": {"company"}, "authorities": {"authority"}}.get(scope, {"company", "authority"})
        orgs = {i: o for i, o in orgs.items() if o["kinds"] & want}
        terms = _norm(q).split()
        score = {i: 1.0 for i, o in orgs.items() if terms and all(w in _norm(o["name"]) for w in terms)}
        from qdrant_client import models as m
        hits = qdrant().query_points(coll("entities"), query=vec, using="description", limit=3 * k, with_payload=["node_id"],
                                     query_filter=m.Filter(must=[m.FieldCondition(key="node_id", match=m.MatchAny(any=list(orgs)))])
                                     if orgs else None).points
        top = max((p.score for p in hits), default=0)
        for p in hits:
            if p.payload["node_id"] in orgs and p.score >= top - MARGIN:
                score.setdefault(p.payload["node_id"], p.score)
        ranked = sorted(score, key=lambda i: (-score[i], orgs[i]["name"] or ""))[:k]
        out["organizations"] = [{"id": i, "name": orgs[i]["name"], "kinds": sorted(orgs[i]["kinds"]), "score": round(score[i], 3),
                                 "tender_ids": sorted(orgs[i]["tender_ids"])} for i in ranked]
    return out


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
                    "located": e.get("located"), "kind": e.get("kind") or "ner", "char_start": a,
                    "before": before, "quote": quote, "after": after})
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
