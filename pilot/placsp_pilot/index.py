"""Index the pilot into our stack's stores: Qdrant (vectors + payload) and Neo4j (graph).

Qdrant, three collections (prefix PILOT_COLLECTION_PREFIX, default pilot_):
- tenders   one point per expediente: the unified Tender object. Every fact from the feed and
            from every document (lots with criteria, requirements, scope, result, bids,
            contracts; guarantees, conditions, modifications, timeline) and the ordered list of
            its documents, linked by sha256, source URL and stored file. Vector: description.
- chunks    every ~512-word chunk of every document, for retrieval. Payload links it back to the
            tender, the document and its position (doc_seq), its pages, and the graph entities
            it mentions. Vector: chunk text.
- entities  graph entities with their GraphRAG descriptions (local search). Vector: description.

Neo4j: the same graph, every node labelled `Pilot` plus `Pilot<Type>` so it never collides with
the app's Company/Lot/Contract constraints. Documents are chained in order (HAS_DOCUMENT {seq},
NEXT_DOCUMENT) and split into Chunk nodes (HAS_CHUNK, NEXT, MENTIONS -> entity); chunk text
stays in Qdrant (qdrant_id on the node).

The index is a projection of pilot.db: each run deletes the pilot namespace and rewrites it, so
the counts in the stores are exactly what validation expects. Embeddings are cached in pilot.db,
so a rerun does not re-embed.
"""
import hashlib
import json
import re
import struct
import time
import uuid
import warnings
from collections import defaultdict
from pathlib import Path

from placsp_pilot.config import PilotConfig
from placsp_pilot.graph import Graph, build
from placsp_pilot.nlpstages import split_words
from placsp_pilot.services import Services
from placsp_pilot.store import Store

NS = uuid.UUID("6f1c3a52-5b0e-4f37-9a1e-7d2b8c4e0a11")
PAGE = re.compile(r"\[Página (\d+)\]")
TENDER_ID = re.compile(r":(\d{5,})(?::|$)")
SKIP_ENTITY_LABELS = {"Tender", "Document", "Notice"}


def point_id(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(map(str, parts))))


def _clean(node: dict, drop=("id", "label", "evidence", "documents", "descriptions", "file_path")) -> dict:
    return {k: v for k, v in node.items() if k not in drop}


# ── chunks ────────────────────────────────────────────────────────────────

def page_ranges(pieces: list[str]) -> list[tuple[int | None, int | None]]:
    """Page span of each chunk from the "[Página N]" markers text extraction leaves in PDFs."""
    out, current = [], None
    for p in pieces:
        marks = [int(m) for m in PAGE.findall(p)]
        start = current if (not marks or not p.lstrip().startswith("[Página")) else marks[0]
        if start is None and marks:
            start = marks[0]
        end = marks[-1] if marks else start
        out.append((start, end))
        current = end
    return out


def chunk_records(cfg: PilotConfig, store: Store, g: Graph, sha: str, text_path: str) -> list[dict]:
    pieces = split_words(Path(text_path).read_text(encoding="utf-8"), cfg.chunk_words)
    ner = {r["idx"]: r for r in store.q("SELECT idx, status, result_json FROM chunk WHERE sha=?", (sha,))}
    names = g.doc_names.get(sha, {})
    out = []
    for i, (piece, (pf, pt)) in enumerate(zip(pieces, page_ranges(pieces))):
        row = ner.get(i)
        ents = []
        if row is not None and row["status"] == "ok":
            for e in json.loads(row["result_json"]).get("entities", []):
                nid = names.get(e["name"])
                if nid and nid not in ents:
                    ents.append(nid)
        out.append({"idx": i, "text": piece, "words": len(piece.split()), "page_from": pf, "page_to": pt,
                    "ner": row["status"] if row is not None else "not_planned", "entity_ids": ents})
    return out


# ── unified tender object ─────────────────────────────────────────────────

def _orgs(g: Graph, ids) -> list[dict]:
    return [{"name": g.nodes[o].get("name"), "nif": g.nodes[o].get("nif"), "id": o} for o in ids if o in g.nodes]


def _bid(g: Graph, b: str) -> dict:
    d = _clean(g.nodes[b])
    d["bidders"] = _orgs(g, g.out(b, "SUBMITTED_BY"))
    d["contracts"] = [_clean(g.nodes[c]) for c in g.out(b, "RESULTED_IN")]
    return d


def tender_object(g: Graph, rec: dict, n_chunks: int) -> dict:
    eid = rec["id"]
    tid = f"tender:{eid}"
    t = g.nodes[tid]
    feed = rec["feed"]
    lots = []
    for lid in sorted(g.out(tid, "HAS_LOT"), key=lambda x: (len(g.nodes[x].get("number") or "zz"), g.nodes[x].get("number") or "")):
        lot = _clean(g.nodes[lid])
        lot["award_criteria"] = [_clean(g.nodes[c]) for c in g.out(lid, "HAS_CRITERION")]
        lot["criteria_points_total"] = sum(c.get("points") or 0 for c in lot["award_criteria"] if c.get("source") == "feed") or \
            sum(c.get("points") or 0 for c in lot["award_criteria"]) or None
        lot["requirements"] = [dict(_clean(g.nodes[r]), label=g.nodes[r]["label"],
                                    qualifications=[g.nodes[q].get("name") for q in g.out(r, "ACCEPTS")])
                               for r in g.out(lid, "REQUIRES")]
        lot["scope"] = [dict(_clean(g.nodes[x]), label=g.nodes[x]["label"]) for x in g.out(lid, "INCLUDES")]
        bids = list(dict.fromkeys(g.out(lid, "RECEIVED_BID") + g.into(lid, "BID_FOR")))
        lot["bids"] = [_bid(g, b) for b in bids]
        res = g.out(lid, "HAS_RESULT")
        if res:
            r = _clean(g.nodes[res[0]])
            r["winners"] = [w for b in g.out(res[0], "WINNER") for w in _orgs(g, g.out(b, "SUBMITTED_BY"))]
            lot["result"] = r
        lot["awarded_to"] = [dict(o, **(g.edge_props(lid, "AWARDED_TO", o["id"]).get("attributes") or {}))
                             for o in _orgs(g, g.out(lid, "AWARDED_TO"))]
        contracts = list(dict.fromkeys(
            [c for b in bids for c in g.out(b, "RESULTED_IN")] + g.into(lid, "CONTRACT_FOR") + g.out(lid, "HAS_CONTRACT")))
        lot["contracts"] = [dict(_clean(g.nodes[c]), contractors=_orgs(g, g.out(c, "SIGNED_WITH") + g.out(c, "CONTRACTOR")))
                            for c in contracts]
        lots.append(lot)

    docs = [{k: v for k, v in d.items() if k not in ("evidence",)} for d in rec["documents"]]
    notices = sorted((_clean(g.nodes[n]) for n in g.out(tid, "HAS_NOTICE")), key=lambda n: n.get("published") or "")
    timeline = [{"date": n.get("published"), "event": f"Anuncio: {n.get('type_label') or n.get('type')}"} for n in notices]
    timeline += [{"date": d["effective_date"], "event": f"Documento {d['seq']}: {d.get('role')} — {d.get('title')}",
                  "doc_seq": d["seq"], "sha256": d.get("sha256")} for d in docs]
    timeline.sort(key=lambda x: (x["date"] or "0000", x.get("doc_seq") or 0))

    company_roles: dict[str, set] = defaultdict(set)
    for lot in lots:
        for b in lot["bids"]:
            for o in b["bidders"]:
                company_roles[o["id"]].add("winner" if b.get("winner") else "bidder")
        for o in lot["awarded_to"]:
            company_roles[o["id"]].add("winner")
        for c in lot["contracts"]:
            for o in c["contractors"]:
                company_roles[o["id"]].add("contractor")
        for b in lot["bids"]:
            for o in b["bidders"]:
                for jv in g.out(o["id"], "MEMBER_OF"):
                    for m in g.into(jv, "MEMBER_OF"):
                        company_roles[m].add("ute_member")
    authority = g.into(tid, "PUBLISHED")

    obj = _clean(t)
    published = obj.get("published")
    obj.update({
        "tender_id": eid, "folder_id": feed.get("folder_id"), "updated": feed.get("updated"),
        "published_at": f"{published}T00:00:00Z" if published else None,
        "authority": _orgs(g, authority)[0] if authority else None,
        "authority_hierarchy": (feed.get("authority") or {}).get("hierarchy"),
        "lots": lots,
        "guarantees": [_clean(g.nodes[x]) for x in g.out(tid, "REQUIRES")],
        "execution_conditions": [_clean(g.nodes[x]) for x in g.out(tid, "HAS_CONDITION")],
        "modifications": [_clean(g.nodes[n]) for n in g.nodes if n.startswith(f"modification:{eid}:")],
        "notices": notices,
        "documents": docs,
        "timeline": timeline,
        "companies": [dict(o, roles=sorted(company_roles[o["id"]])) for o in _orgs(g, company_roles)],
        "company_nifs": sorted({g.nodes[o].get("nif") for o in company_roles if g.nodes.get(o, {}).get("nif")}),
        "winner_nifs": sorted({g.nodes[o].get("nif") for o, r in company_roles.items() if "winner" in r and g.nodes.get(o, {}).get("nif")}),
        "counts": {"lots": len(lots), "documents": len(docs), "notices": len(notices), "chunks": n_chunks,
                   "entities": sum(d.get("entities") or 0 for d in docs), "relations": sum(d.get("relations") or 0 for d in docs)},
    })
    return obj


# ── embeddings with a cache in pilot.db ───────────────────────────────────

class Embedder:
    def __init__(self, cfg: PilotConfig, store: Store):
        if not cfg.vectorizer_url:
            raise SystemExit("VECTORIZER_URL is not set: indexing needs the BGE-M3 vectorizer")
        self.cfg, self.store = cfg, store
        self.svc = Services(cfg, store, need_nlp=False)
        with store.tx() as c:
            c.execute("CREATE TABLE IF NOT EXISTS embedding (key TEXT PRIMARY KEY, dim INTEGER, vector BLOB)")
        self.dim = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        have = {}
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            for r in self.store.q(f"SELECT key, dim, vector FROM embedding WHERE key IN ({','.join('?' * len(part))})", part):
                have[r["key"]] = list(struct.unpack(f"{r['dim']}f", r["vector"]))
        missing = [i for i, k in enumerate(keys) if k not in have]
        for i in range(0, len(missing), self.cfg.embed_batch):
            idx = missing[i:i + self.cfg.embed_batch]
            vecs = self.svc.embed([texts[j][:8000] for j in idx])
            with self.store.tx() as c:
                c.executemany("INSERT OR REPLACE INTO embedding (key, dim, vector) VALUES (?,?,?)",
                              [(keys[j], len(v), struct.pack(f"{len(v)}f", *v)) for j, v in zip(idx, vecs)])
            for j, v in zip(idx, vecs):
                have[keys[j]] = v
        out = [have[k] for k in keys]
        if out:
            self.dim = len(out[0])
        return out


# ── Qdrant ────────────────────────────────────────────────────────────────

COLLECTIONS = {
    "tenders": ("description", {
        "tender_id": "keyword", "channel": "keyword", "status": "keyword", "contract_type": "keyword",
        "procedure": "keyword", "cpv": "keyword", "nuts": "keyword", "published_at": "datetime", "value": "float",
        "authority.nif": "keyword", "company_nifs": "keyword", "winner_nifs": "keyword", "analysable": "bool",
        "documents[].role": "keyword", "documents[].sha256": "keyword"}),
    "chunks": ("text", {
        "tender_id": "keyword", "doc_sha256": "keyword", "doc_role": "keyword", "doc_seq": "integer",
        "channel": "keyword", "chunk_idx": "integer", "entity_ids": "keyword", "effective_date": "keyword"}),
    "entities": ("description", {
        "node_id": "keyword", "label": "keyword", "tender_ids": "keyword", "nif": "keyword"}),
}


class QdrantIndex:
    def __init__(self, cfg: PilotConfig):
        from qdrant_client import QdrantClient, models
        warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        self.m = models
        self.client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key or None, timeout=300)
        self.prefix = cfg.collection_prefix

    def name(self, short: str) -> str:
        return f"{self.prefix}{short}"

    def recreate(self, short: str, dim: int):
        m = self.m
        name = self.name(short)
        vector, indexes = COLLECTIONS[short]
        if self.client.collection_exists(name):
            self.client.delete_collection(name)
        self.client.create_collection(name, vectors_config={vector: m.VectorParams(size=dim, distance=m.Distance.COSINE)})
        kinds = {"keyword": m.PayloadSchemaType.KEYWORD, "integer": m.PayloadSchemaType.INTEGER,
                 "float": m.PayloadSchemaType.FLOAT, "datetime": m.PayloadSchemaType.DATETIME, "bool": m.PayloadSchemaType.BOOL}
        for field, kind in indexes.items():
            self.client.create_payload_index(name, field_name=field, field_schema=kinds[kind], wait=True)

    def upsert(self, short: str, points: list[tuple[str, list[float], dict]]):
        vector = COLLECTIONS[short][0]
        for i in range(0, len(points), 128):
            self.client.upsert(self.name(short), wait=True, points=[
                self.m.PointStruct(id=pid, vector={vector: vec}, payload=payload) for pid, vec, payload in points[i:i + 128]])

    def count(self, short: str, **match) -> int:
        flt = None
        if match:
            flt = self.m.Filter(must=[self.m.FieldCondition(key=k, match=self.m.MatchValue(value=v)) for k, v in match.items()])
        return self.client.count(self.name(short), count_filter=flt, exact=True).count

    def get(self, short: str, pid: str):
        r = self.client.retrieve(self.name(short), ids=[pid], with_payload=True)
        return r[0].payload if r else None


# ── Neo4j ─────────────────────────────────────────────────────────────────

_REL = re.compile(r"[^A-Z0-9_]")


def neo_props(d: dict) -> dict:
    """Neo4j properties are primitives or homogeneous lists of primitives; anything else is JSON."""
    out = {}
    for k, v in d.items():
        if v is None or k in ("id", "label"):
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            out[k] = v
        elif isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            out[k] = v
        elif v not in ([], {}):
            out[k] = json.dumps(v, ensure_ascii=False)
    return out


class Neo4jIndex:
    def __init__(self, cfg: PilotConfig):
        from neo4j import GraphDatabase
        if not cfg.neo4j_password:
            raise SystemExit("NEO4J_PASSWORD is not set")
        self.driver = GraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))
        self.prefix = cfg.neo4j_label_prefix
        self.base = cfg.neo4j_label_prefix  # common label on every pilot node

    def run(self, q: str, **kw):
        with self.driver.session() as s:
            return list(s.run(q, **kw))

    def reset(self):
        self.run(f"CREATE CONSTRAINT {self.base.lower()}_node_id IF NOT EXISTS FOR (n:`{self.base}`) REQUIRE n.id IS UNIQUE")
        self.run(f"MATCH (n:`{self.base}`) CALL (n) {{ DETACH DELETE n }} IN TRANSACTIONS OF 5000 ROWS")

    def write_nodes(self, nodes: list[dict]):
        by_label = defaultdict(list)
        for n in nodes:
            by_label[n["label"]].append({"id": n["id"], "props": neo_props(n)})
        for label, rows in by_label.items():
            lab = f"{self.prefix}{re.sub(r'[^A-Za-z0-9]', '', label)}"
            for i in range(0, len(rows), 2000):
                self.run(f"UNWIND $rows AS r MERGE (n:`{self.base}` {{id: r.id}}) SET n += r.props, n:`{lab}`",
                         rows=rows[i:i + 2000])

    def write_edges(self, edges: list[dict]):
        by_rel = defaultdict(list)
        for e in edges:
            props = {k: v for k, v in e.items() if k not in ("src", "dst", "rel")}
            by_rel[_REL.sub("_", e["rel"].upper())].append({"src": e["src"], "dst": e["dst"], "props": neo_props(props)})
        for rel, rows in by_rel.items():
            keyed = [r for r in rows if "tender" in r["props"]]
            plain = [r for r in rows if "tender" not in r["props"]]
            for subset, key in ((plain, ""), (keyed, " {tender: r.props.tender}")):
                for i in range(0, len(subset), 2000):
                    self.run(f"UNWIND $rows AS r MATCH (a:`{self.base}` {{id: r.src}}) MATCH (b:`{self.base}` {{id: r.dst}})"
                             f" MERGE (a)-[e:`{rel}`{key}]->(b) SET e += r.props", rows=subset[i:i + 2000])


# ── stage ─────────────────────────────────────────────────────────────────

def _tender_ids(g: Graph, exp_of_sha: dict[str, set]) -> dict[str, set]:
    """Which expedientes each node belongs to: its own id, its documents, else its neighbours'."""
    out: dict[str, set] = defaultdict(set)
    for nid, n in g.nodes.items():
        m = TENDER_ID.search(nid)
        if m and not nid.startswith(("org:", "jv:", "qualification:", "doc:")):
            out[nid].add(m.group(1))
        for sha in n.get("documents", []):
            out[nid] |= exp_of_sha.get(sha, set())
    for e in g.edges:
        for a, b in ((e["src"], e["dst"]), (e["dst"], e["src"])):
            if a.startswith(("org:", "jv:", "qualification:")) and out.get(b):
                out[a] |= out[b]
    return out


def index(cfg: PilotConfig, store: Store):
    emb = Embedder(cfg, store)
    qd = QdrantIndex(cfg)
    neo = Neo4jIndex(cfg)
    with store.tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS indexed (exp_id TEXT PRIMARY KEY, documents INTEGER, chunks INTEGER,"
                  " entities INTEGER, payload_bytes INTEGER, ms INTEGER)")
        c.execute("DELETE FROM indexed")
    with store.stage("index") as st:
        g = build(cfg, store)                          # also rewrites out/ (JSON per expediente, nodes/edges)
        recs = {}
        for f in (cfg.out_dir / "expedientes").glob("*.json"):
            r = json.loads(f.read_text(encoding="utf-8"))
            recs[r["id"]] = r
        exp_of_sha = defaultdict(set)
        for r in store.q("SELECT DISTINCT sha, exp_id FROM docref WHERE status='fetched' AND sha IS NOT NULL"):
            exp_of_sha[r["sha"]].add(r["exp_id"])

        t0 = time.time()
        dim = len(emb.embed(["dimension probe"])[0])
        for short in COLLECTIONS:
            qd.recreate(short, dim)
        neo.reset()

        chunk_nodes, chunk_edges, entity_points = [], [], []
        for eid, rec in sorted(recs.items()):
            te = time.time()
            points = []
            prev_chunk = None
            for d in rec["documents"]:
                if d.get("text_status") != "ok" or not d.get("file_path"):
                    continue
                tp = store.one("SELECT text_path FROM blob WHERE sha=?", (d["sha256"],))
                if not tp or not tp["text_path"]:
                    continue
                for ch in chunk_records(cfg, store, g, d["sha256"], tp["text_path"]):
                    pid = point_id("chunk", eid, d["sha256"], ch["idx"])
                    points.append((pid, ch["text"], {
                        "chunk_id": pid, "tender_id": eid, "folder_id": rec["folder_id"], "channel": rec["channel"],
                        "doc_sha256": d["sha256"], "doc_seq": d["seq"], "doc_role": d.get("role"), "doc_title": d.get("title"),
                        "doc_url": d.get("url"), "effective_date": d.get("effective_date"), "chunk_idx": ch["idx"],
                        "page_from": ch["page_from"], "page_to": ch["page_to"], "words": ch["words"], "ner": ch["ner"],
                        "entity_ids": ch["entity_ids"], "text": ch["text"]}))
                    cid = f"chunk:{d['sha256']}:{ch['idx']}"
                    chunk_nodes.append({"id": cid, "label": "Chunk", "idx": ch["idx"], "doc_sha256": d["sha256"],
                                        "page_from": ch["page_from"], "page_to": ch["page_to"], "words": ch["words"],
                                        "ner": ch["ner"], "qdrant_id": pid, "tender_id": eid})
                    chunk_edges.append({"src": f"doc:{d['sha256']}", "rel": "HAS_CHUNK", "dst": cid, "idx": ch["idx"]})
                    if prev_chunk and prev_chunk.startswith(f"chunk:{d['sha256']}:"):
                        chunk_edges.append({"src": prev_chunk, "rel": "NEXT", "dst": cid})
                    for nid in ch["entity_ids"]:
                        chunk_edges.append({"src": cid, "rel": "MENTIONS", "dst": nid})
                    prev_chunk = cid
            vecs = emb.embed([p[1] for p in points]) if points else []
            qd.upsert("chunks", [(pid, v, payload) for (pid, _, payload), v in zip(points, vecs)])

            obj = tender_object(g, rec, len(points))
            desc = obj.get("description") or ""
            [tvec] = emb.embed([f"{obj.get('name') or ''}\n{desc}"])
            qd.upsert("tenders", [(point_id("tender", eid), tvec, obj)])
            payload_bytes = len(json.dumps(obj, ensure_ascii=False))
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO indexed (exp_id, documents, chunks, entities, payload_bytes, ms) VALUES (?,?,?,?,?,?)",
                          (eid, len(rec["documents"]), len(points), obj["counts"]["entities"], payload_bytes,
                           int((time.time() - te) * 1000)))
            st["items"] += 1
            print(time.strftime("%H:%M:%S"), f"index {st['items']}/{len(recs)} {eid}: {len(points)} chunks", flush=True)

        owners = _tender_ids(g, exp_of_sha)
        ents = [n for n in g.nodes.values() if n["label"] not in SKIP_ENTITY_LABELS and (n.get("description") or n.get("name"))]
        texts = [f"{n['label']}: {n.get('name') or ''}\n{n.get('description') or ''}".strip() for n in ents]
        vecs = emb.embed(texts)
        for n, v in zip(ents, vecs):
            entity_points.append((point_id("entity", n["id"]), v, {
                "node_id": n["id"], "label": n["label"], "name": n.get("name"), "subtype": n.get("subtype"),
                "nif": n.get("nif"), "description": n.get("description"), "tender_ids": sorted(owners.get(n["id"], ())),
                **{k: v for k, v in _clean(n).items() if isinstance(v, (int, float, str, bool)) and k not in ("description", "name")}}))
        qd.upsert("entities", entity_points)

        chunk_nodes = list({n["id"]: n for n in chunk_nodes}.values())   # a document shared by two tenders: one node
        neo.write_nodes(list(g.nodes.values()) + chunk_nodes)
        neo.write_edges(g.edges + chunk_edges)
        st["notes"] = json.dumps({"chunk_nodes": len(chunk_nodes), "entity_points": len(entity_points),
                                  "graph_nodes": len(g.nodes), "graph_edges": len(g.edges), "dim": dim,
                                  "write_s": round(time.time() - t0, 1)})
        print(time.strftime("%H:%M:%S"), f"index: {len(recs)} tenders, {len(chunk_nodes)} chunks, {len(entity_points)} entities;"
              f" neo4j {len(g.nodes) + len(chunk_nodes)} nodes, {len(g.edges) + len(chunk_edges)} edges", flush=True)
