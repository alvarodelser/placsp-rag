"""Validate every expediente end to end and record the result.

Each check compares an expected value, recomputed from pilot.db and the files on disk, with the
actual one (in pilot.db, the graph, Qdrant or Neo4j). Results go to the `validation` table,
out/validation.json and out/validation.csv; the report summarises them.

Levels: fail = the pilot did not do its job for this expediente (missing download, missing NLP
output, wrong index count); warn = the data itself is incomplete (no CPV, criteria that do not
add up to 100, a pliego the authority never published) and is recorded, not fixed.
"""
import base64
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from placsp_pilot import classify as C
from placsp_pilot.config import PilotConfig
from placsp_pilot.index import Neo4jIndex, QdrantIndex, point_id
from placsp_pilot.nlpstages import split_words
from placsp_pilot.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS validation (
    exp_id   TEXT NOT NULL,
    check_id TEXT NOT NULL,
    level    TEXT NOT NULL,          -- fail | warn: severity if the check does not pass
    status   TEXT NOT NULL,          -- pass | warn | fail | skip
    expected TEXT,
    actual   TEXT,
    detail   TEXT,
    at       REAL,
    PRIMARY KEY (exp_id, check_id)
);
"""
TENDERING = ("placsp_mayores", "externos_mayores")


class Recorder:
    def __init__(self, exp_id: str):
        self.exp_id, self.rows = exp_id, []

    def check(self, check_id: str, ok: bool | None, level: str = "fail", expected="", actual="", detail=""):
        status = "skip" if ok is None else ("pass" if ok else level)
        self.rows.append((self.exp_id, check_id, level, status, str(expected), str(actual), str(detail)[:1000], time.time()))


def _sha1_b64(path: str) -> str:
    return base64.b64encode(hashlib.sha1(Path(path).read_bytes()).digest()).decode()


def _feed_checks(r: Recorder, e, t: dict):
    tender = t.get("tender", {})
    missing = [k for k, v in {"folder_id": t.get("folder_id"), "title": tender.get("name") or t.get("atom_title"),
                              "authority": (t.get("authority") or {}).get("name"), "status": t.get("status")}.items() if not v]
    r.check("feed.identity", not missing, "fail", "folder_id,title,authority,status", "missing: " + ",".join(missing) if missing else "all")
    needed = {"contract_type": tender.get("contract_type")}
    if e["channel"] != "propios":
        needed["procedure"] = tender.get("procedure")
    missing = [k for k, v in needed.items() if not v]
    r.check("feed.classification", not missing, "fail", ",".join(needed), "missing: " + ",".join(missing) if missing else "all")
    r.check("feed.amount", bool(tender.get("value_estimated") or tender.get("budget_tax_excl")), "warn",
            "value or budget", tender.get("value_estimated") or tender.get("budget_tax_excl"))
    r.check("feed.cpv", bool(tender.get("cpv")), "warn", ">=1", len(tender.get("cpv") or []))
    r.check("feed.lots", len(t.get("lots", [])) >= 1, "fail", ">=1", len(t.get("lots", [])))
    dated = [n for n in t.get("notices", []) if n.get("published")]
    r.check("feed.notices", bool(dated), "fail", ">=1 dated notice", len(dated))
    crit = t.get("award_criteria", [])
    if e["channel"] in TENDERING and crit:
        bad = []
        for lot in t.get("lots", []):
            total = sum(c.get("points") or 0 for c in crit if c.get("lot") in (None, lot["number"]))
            if abs(total - 100) > 0.01:
                bad.append(f"lote {lot['number']}: {total:g}")
        r.check("feed.criteria_points", not bad, "warn", "100 per lot", "; ".join(bad) or "100")
    else:
        r.check("feed.criteria_points", None, "warn", "100 per lot", "no criteria in feed")
    status = (t.get("status") or {}).get("code")
    if status in ("ADJ", "RES"):
        results = t.get("results", [])
        winners = sum(len(x.get("winners", [])) for x in results)
        void = all((x.get("result") or {}).get("code") in ("3", "4", "5", "6", "7") for x in results) if results else False
        r.check("feed.result", bool(results) and (winners > 0 or void), "warn", "result with winner", f"{len(results)} results, {winners} winners")
    else:
        r.check("feed.result", None, "warn", "result with winner", f"status {status}")


def _doc_checks(r: Recorder, store: Store, e, rec: dict | None):
    eid = e["id"]
    refs = store.q("SELECT d.*, b.path, b.text_status FROM docref d LEFT JOIN blob b ON b.sha=d.sha WHERE d.exp_id=?", (eid,))
    expected = [x for x in refs if x["status"] != "skipped" or (x["error"] or "").startswith("too_large")]
    fetched = [x for x in refs if x["status"] == "fetched"]
    # The source answering 4xx/5xx is the platform's problem, recorded apart from the pilot's own failures.
    source = [f"{x['label']}: {x['error']}" for x in refs if x["status"] == "failed" and (x["error"] or "").startswith("http_")]
    failed = [f"{x['label']}: {x['error']}" for x in refs
              if x["status"] == "pending" or (x["status"] == "failed" and not (x["error"] or "").startswith("http_"))]
    r.check("docs.fetched", not failed, "fail", len(expected) - len(source), len(fetched), "; ".join(failed[:5]))
    r.check("docs.source_errors", not source, "warn", 0, len(source), "; ".join(source[:5]))
    hashed = [x for x in fetched if x["feed_hash"] and x["path"]]
    bad = [x["label"] for x in hashed if _sha1_b64(x["path"]) != x["feed_hash"]]
    r.check("docs.hash", (not bad) if hashed else None, "fail", len(hashed), len(hashed) - len(bad), "; ".join(bad[:5]))
    roles = {x["role"] for x in fetched}
    if e["channel"] in TENDERING and (json.loads(e["tender_json"]).get("status") or {}).get("code") != "PRE":
        r.check("docs.pcap", bool(roles & {C.PCAP, C.PCAP_PPT}), "warn", "PCAP", ",".join(sorted(roles & {C.PCAP, C.PCAP_PPT})) or "none")
        r.check("docs.ppt", bool(roles & {C.PPT, C.PCAP_PPT, C.PROJECT}), "warn", "PPT", ",".join(sorted(roles & {C.PPT, C.PCAP_PPT, C.PROJECT})) or "none")
    else:
        r.check("docs.pcap", None, "warn", "PCAP", "no pliegos in this channel/status")
        r.check("docs.ppt", None, "warn", "PPT", "no pliegos in this channel/status")
    blobs = {x["sha"]: x["text_status"] for x in fetched}
    not_text = Counter(s for s in blobs.values() if s not in ("ok", "archive"))
    r.check("docs.text", not not_text, "warn", len(blobs), sum(1 for s in blobs.values() if s in ("ok", "archive")),
            ", ".join(f"{k} {v}" for k, v in not_text.items()))
    if rec is None:
        r.check("docs.order", False, "fail", "ordered documents", "no graph output")
        return
    docs = rec["documents"]
    seqs = [d["seq"] for d in docs]
    dates = [d["effective_date"] or "0000" for d in docs]
    r.check("docs.order", seqs == list(range(1, len(docs) + 1)) and dates == sorted(dates) and len(docs) == len(blobs),
            "fail", f"1..{len(blobs)} by date", f"{len(docs)} docs, seq ok={seqs == list(range(1, len(docs) + 1))}, dates sorted={dates == sorted(dates)}")
    undated = [d.get("filename") for d in docs if d["date_source"] == "none"]
    r.check("docs.dated", not undated, "warn", len(docs), len(docs) - len(undated), "; ".join(map(str, undated[:5])))


def _nlp_checks(r: Recorder, store: Store, cfg: PilotConfig, eid: str):
    shas = [x["sha"] for x in store.q("SELECT DISTINCT d.sha FROM docref d JOIN blob b ON b.sha=d.sha"
                                      " WHERE d.exp_id=? AND d.status='fetched' AND b.text_status='ok'", (eid,))]
    if not shas:
        for c in ("nlp.summary", "nlp.ner"):
            r.check(c, None, "fail", 0, 0, "no text documents")
    else:
        q = ",".join("?" * len(shas))
        blobs = {b["sha"]: b for b in store.q(f"SELECT * FROM blob WHERE sha IN ({q})", shas)}
        ok = sum(1 for b in blobs.values() if b["summary_status"] == "ok")
        r.check("nlp.summary", ok == len(shas), "fail", len(shas), ok)
        ch = store.one(f"SELECT SUM(selected) sel, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) ok FROM chunk WHERE sha IN ({q})", shas)
        not_planned = [b["sha"][:10] for b in blobs.values() if b["ner_status"] == "pending"]
        r.check("nlp.ner", (ch["sel"] or 0) == (ch["ok"] or 0) and not not_planned, "fail", ch["sel"] or 0, ch["ok"] or 0,
                f"not chunked: {len(not_planned)}" if not_planned else "")
    agg = store.one("SELECT status FROM extraction WHERE exp_id=? AND kind='tender_description'", (eid,))
    r.check("nlp.tender_description", bool(agg and agg["status"] == "ok"), "fail", "ok", agg["status"] if agg else "missing")


def _entity_checks(r: Recorder, store: Store, cfg: PilotConfig, eid: str):
    """No duplicates, every mention placed and traceable, every entity described and refined."""
    from placsp_pilot.entities import REFINE_TYPES, same_codes, schema, similarity, typo_equal
    from placsp_pilot.graph import norm_name
    schema(store)
    res = store.one("SELECT status, error FROM resolution WHERE exp_id=?", (eid,))
    r.check("entities.resolved", bool(res and res["status"] == "ok"), "fail" if not res or res["status"] == "failed" else "warn",
            "ok", res["status"] if res else "missing", (res["error"] or "") if res else "")
    total = store.one("SELECT COUNT(*) n, SUM(located) loc FROM mention WHERE kind='ner' AND sha IN"
                      " (SELECT sha FROM docref WHERE exp_id=? AND status='fetched')", (eid,))
    linked = store.one("SELECT COUNT(*) n FROM entity_mention em JOIN mention m ON m.id=em.mention_id"
                       " WHERE em.exp_id=? AND m.kind='ner'", (eid,))["n"]
    r.check("entities.mentions", linked == total["n"], "fail", total["n"], linked, "mentions placed on an entity")
    co = store.one("SELECT status, links, error FROM coref_run WHERE exp_id=?", (eid,))
    r.check("entities.coref", bool(co and co["status"] == "ok"), "fail", "ok", co["status"] if co else "missing",
            f"{co['links']} references linked" if co else "")
    loc = (total["loc"] or 0) / total["n"] if total["n"] else 1.0
    r.check("entities.located", loc >= 0.9, "warn", ">=90% quotes found in their chunk", f"{loc:.0%}")
    ents = store.q("SELECT * FROM entity WHERE exp_id=?", (eid,))
    keys = Counter((x["type"], norm_name(x["name"])) for x in ents)
    dupes = [f"{t}: {n}" for (t, n), c in keys.items() if c > 1]
    r.check("entities.duplicates", not dupes, "fail", 0, len(dupes), "; ".join(dupes[:8]))
    near = []
    by_type = defaultdict(list)
    for x in ents:
        by_type[x["type"]].append(x)
    for typ, xs in by_type.items():
        for i, a in enumerate(xs):
            for b in xs[i + 1:]:
                # The pairs resolution should have merged: same words up to typos, or nearly the same string.
                if not (a["anchor"] and b["anchor"]) and (typo_equal(a["name"], b["name"]) or (similarity(a["name"], b["name"]) >= 0.95 and same_codes(a["name"], b["name"]))):
                    near.append(f"{typ}: {a['name']} ~ {b['name']}")
    r.check("entities.near_duplicates", not near, "warn", 0, len(near), "; ".join(near[:8]))
    desc = {(x["kind"], x["item_id"]) for x in store.q(
        "SELECT kind, item_id FROM entity_description WHERE status='ok' AND exp_id IN (?, '*')", (eid,))}
    undescribed = [x["name"] for x in ents if ("entity", x["id"]) not in desc]
    r.check("entities.described", not undescribed, "fail", len(ents), len(ents) - len(undescribed), "; ".join(map(str, undescribed[:8])))
    if cfg.describe_relations:
        rels = store.q("SELECT id FROM entity_relation WHERE exp_id=? AND type != 'DETAILED_BY'", (eid,))
        missing = [x["id"] for x in rels if ("relation", x["id"]) not in desc]
        r.check("entities.relations_described", not missing, "fail", len(rels), len(rels) - len(missing))
    want = [x for x in ents if x["type"] in REFINE_TYPES]
    got = {x["entity_id"] for x in store.q("SELECT entity_id FROM refinement WHERE exp_id=? AND status='ok'", (eid,))}
    r.check("entities.refined", all(x["id"] in got for x in want), "fail", len(want), sum(1 for x in want if x["id"] in got))
    # A requirement whose passages state a figure should come out with that figure.
    refined = {x["entity_id"]: json.loads(x["result_json"]) for x in store.q(
        "SELECT entity_id, result_json FROM refinement WHERE exp_id=? AND status='ok'", (eid,))}
    missing_fig = []
    for x in ents:
        if x["type"] != "REQUIREMENT":
            continue
        quotes = " ".join(m["evidence"] or "" for m in store.q(
            "SELECT m.evidence FROM entity_mention em JOIN mention m ON m.id=em.mention_id WHERE em.exp_id=? AND em.entity_id=?",
            (eid, x["id"])))
        attrs = {**json.loads(x["attributes"] or "{}"), **refined.get(x["id"], {})}
        if re.search(r"\d[\d.,]*\s*(€|euros?|%|años|contratos|personas|veces)", quotes, re.I) and not any(
                attrs.get(k) is not None for k in ("threshold_amount", "amount", "years", "technicians", "standard")):
            missing_fig.append(x["name"])
    r.check("requirements.figures", not missing_fig, "warn", 0, len(missing_fig), "; ".join(missing_fig[:8]))
    conflicts = [f"{x['name']}: {', '.join(json.loads(x['conflicts']))}" for x in ents if json.loads(x["conflicts"] or "{}")]
    r.check("entities.conflicts", not conflicts, "warn", 0, len(conflicts), "; ".join(conflicts[:8]))


def _expected_chunks(cfg: PilotConfig, store: Store, rec: dict) -> tuple[int, int]:
    """(chunk points for this tender, distinct chunk nodes of its documents), recomputed from text."""
    total = 0
    for d in rec["documents"]:
        if d.get("text_status") != "ok":
            continue
        tp = store.one("SELECT text_path FROM blob WHERE sha=?", (d["sha256"],))
        if tp and tp["text_path"]:
            total += len(split_words(Path(tp["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words))
    return total, total


def _graph_and_index_checks(r: Recorder, cfg: PilotConfig, store: Store, rec: dict, qd, neo):
    eid = rec["id"]
    t = rec["feed"]
    nodes = {n["id"]: n for n in rec.get("graph", {}).get("nodes", [])}
    doc_lots = [n for n, x in nodes.items() if x["label"] == "Lot" and x.get("source") == "documents"]
    r.check("graph.lots_mapped", not doc_lots, "warn", "every document lot maps to a feed lot", f"{len(doc_lots)} unmapped",
            "; ".join(nodes[n].get("name") or "" for n in doc_lots[:5]))
    n_docs = len(rec["documents"])
    exp_chunks, exp_chunk_nodes = _expected_chunks(cfg, store, rec)

    payload = qd.get("tenders", point_id("tender", eid)) if qd else None
    if qd is None:
        r.check("qdrant.tender", None, "fail", "point", "Qdrant not reachable")
    else:
        if payload is None:
            r.check("qdrant.tender", False, "fail", "point", "missing")
        else:
            seqs = [d["seq"] for d in payload.get("documents", [])]
            ok = (payload["counts"]["documents"] == n_docs and seqs == list(range(1, n_docs + 1))
                  and len(payload.get("lots", [])) >= len(t.get("lots", [])) and payload.get("folder_id") == t.get("folder_id"))
            r.check("qdrant.tender", ok, "fail", f"{n_docs} docs in order, {len(t.get('lots', []))} lots",
                    f"{payload['counts']['documents']} docs, {len(payload.get('lots', []))} lots")
            winners_feed = sum(len(x.get("winners", [])) for x in t.get("results", []))
            winners_obj = sum(len((l.get("result") or {}).get("winners", [])) for l in payload.get("lots", []))
            r.check("qdrant.tender.winners", winners_obj >= winners_feed if winners_feed else None, "fail",
                    winners_feed, winners_obj)
            r.check("qdrant.tender.description", bool(payload.get("description")), "fail", "description", bool(payload.get("description")))
        got = qd.count("chunks", tender_id=eid)
        r.check("qdrant.chunks", got == exp_chunks, "fail", exp_chunks, got)
    if neo is None:
        r.check("neo4j.tender", None, "fail", "node", "Neo4j not reachable")
        return
    b = neo.base
    rows = neo.run(f"""
        MATCH (t:`{b}` {{id: $tid}})
        OPTIONAL MATCH (t)-[hd:HAS_DOCUMENT]->(d)
        WITH t, count(d) AS docs, collect(hd.seq) AS seqs
        OPTIONAL MATCH (t)-[:HAS_LOT]->(l)
        WITH t, docs, seqs, count(DISTINCT l) AS lots
        OPTIONAL MATCH (t)-[:HAS_DOCUMENT]->(:`{b}`)-[:HAS_CHUNK]->(c)
        WITH t, docs, seqs, lots, count(DISTINCT c) AS chunks
        OPTIONAL MATCH ()-[nx:NEXT_DOCUMENT {{tender: $eid}}]->()
        WITH docs, seqs, lots, chunks, count(nx) AS chain
        OPTIONAL MATCH ()-[mi:MENTIONED_IN {{tender: $eid}}]->()
        RETURN docs, seqs, lots, chunks, chain, count(mi) AS mentions""", tid=f"tender:{eid}", eid=eid)
    if not rows:
        r.check("neo4j.tender", False, "fail", "node", "missing")
        return
    x = rows[0]
    ok = x["docs"] == n_docs and sorted(x["seqs"]) == list(range(1, n_docs + 1)) and x["chain"] == max(0, n_docs - 1)
    r.check("neo4j.documents", ok, "fail", f"{n_docs} docs, chain {max(0, n_docs - 1)}", f"{x['docs']} docs, chain {x['chain']}")
    r.check("neo4j.lots", x["lots"] >= len(t.get("lots", [])), "fail", len(t.get("lots", [])), x["lots"])
    r.check("neo4j.chunks", x["chunks"] == exp_chunk_nodes, "fail", exp_chunk_nodes, x["chunks"])
    linked = store.one("SELECT COUNT(*) n FROM entity_mention WHERE exp_id=?", (eid,))["n"]
    r.check("neo4j.provenance", x["mentions"] == linked, "fail", linked, x["mentions"], "MENTIONED_IN edges, one per mention")


def validate(cfg: PilotConfig, store: Store):
    with store.tx() as c:
        c.executescript(SCHEMA)
        c.execute("DELETE FROM validation")
    try:
        qd = QdrantIndex(cfg)
        qd.client.get_collections()
    except Exception as e:  # noqa: BLE001
        print(f"validate: Qdrant not reachable ({e}); index checks skipped")
        qd = None
    try:
        neo = Neo4jIndex(cfg)
        neo.run("RETURN 1")
    except BaseException as e:  # noqa: BLE001 - SystemExit when NEO4J_PASSWORD is unset
        print(f"validate: Neo4j not reachable ({e}); index checks skipped")
        neo = None
    exp_dir = cfg.out_dir / "expedientes"
    all_rows = []
    with store.stage("validate") as st:
        exps = store.q("SELECT * FROM expediente ORDER BY channel, id")
        for e in exps:
            r = Recorder(e["id"])
            t = json.loads(e["tender_json"])
            path = exp_dir / f"{e['id']}.json"
            rec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            _feed_checks(r, e, t)
            _doc_checks(r, store, e, rec)
            _nlp_checks(r, store, cfg, e["id"])
            _entity_checks(r, store, cfg, e["id"])
            if rec is not None:
                _graph_and_index_checks(r, cfg, store, rec, qd, neo)
            with store.tx() as c:
                c.executemany("INSERT OR REPLACE INTO validation VALUES (?,?,?,?,?,?,?,?)", r.rows)
            all_rows += r.rows
            st["items"] += 1
        # Corpus-level counts.
        g = Recorder("*")
        if qd is not None:
            g.check("qdrant.tenders.total", qd.count("tenders") == len(exps), "fail", len(exps), qd.count("tenders"))
        if neo is not None:
            n = neo.run(f"MATCH (t:`{neo.prefix}Tender`) RETURN count(t) AS n")[0]["n"]
            g.check("neo4j.tenders.total", n == len(exps), "fail", len(exps), n)
        with store.tx() as c:
            c.executemany("INSERT OR REPLACE INTO validation VALUES (?,?,?,?,?,?,?,?)", g.rows)
        all_rows += g.rows

    cols = ["exp_id", "check_id", "level", "status", "expected", "actual", "detail", "at"]
    with (cfg.out_dir / "validation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(all_rows)
    summary = defaultdict(Counter)
    for row in all_rows:
        summary[row[1]][row[3]] += 1
    (cfg.out_dir / "validation.json").write_text(json.dumps(
        {"summary": {k: dict(v) for k, v in sorted(summary.items())},
         "rows": [dict(zip(cols, row)) for row in all_rows]}, ensure_ascii=False, indent=1), encoding="utf-8")
    fails = sum(1 for row in all_rows if row[3] == "fail")
    warns = sum(1 for row in all_rows if row[3] == "warn")
    print(f"validate: {len(exps)} expedientes, {len(all_rows)} checks, {fails} fail, {warns} warn -> out/validation.csv")
