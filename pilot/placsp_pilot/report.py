"""Times and volumes of a pilot run, computed from pilot.db and the run directory."""
import json
import os
import platform
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from lxml import etree

from placsp_pilot.config import PilotConfig
from placsp_pilot.store import Store

MB = 2**20


def _du(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _dist(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": xs[0], "median": statistics.median(xs), "p90": xs[int(0.9 * (len(xs) - 1))],
            "max": xs[-1], "mean": sum(xs) / len(xs), "sum": sum(xs)}


def _feed_rate(cfg: PilotConfig) -> dict:
    """Entries per day seen in the downloaded head pages, per channel (feed updates, not only new tenders)."""
    out = {}
    for f in cfg.raw_dir.glob("feed_*_1.atom"):
        channel = f.stem[len("feed_"):-2]
        ts = [e.text[:19] for e in etree.parse(str(f)).getroot().iter("{http://www.w3.org/2005/Atom}updated")][1:]
        ts = sorted(datetime.fromisoformat(t) for t in ts if t)
        if len(ts) > 1:
            days = max((ts[-1] - ts[0]).total_seconds() / 86400, 1 / 24)
            out[channel] = round(len(ts) / days, 1)
    return out


def _index_stats(store: Store) -> dict:
    if not store.one("SELECT name FROM sqlite_master WHERE name='indexed'"):
        return {}
    r = store.one("SELECT COUNT(*) tenders, SUM(documents) documents, SUM(chunks) chunks, SUM(payload_bytes) payload,"
                  " MAX(payload_bytes) max_payload, SUM(ms) ms FROM indexed")
    notes = store.one("SELECT notes FROM stage_run WHERE stage='index' ORDER BY id DESC LIMIT 1")
    emb = store.one("SELECT COUNT(*) n, SUM(length(vector)) bytes FROM embedding") if store.one(
        "SELECT name FROM sqlite_master WHERE name='embedding'") else None
    return dict(dict(r), **(json.loads(notes["notes"]) if notes and notes["notes"] else {}),
                embeddings_cached=emb["n"] if emb else 0, embedding_bytes=emb["bytes"] if emb else 0)


def _validation(store: Store) -> dict:
    if not store.one("SELECT name FROM sqlite_master WHERE name='validation'"):
        return {}
    by_check = {}
    for r in store.q("SELECT check_id, level, status, COUNT(*) n FROM validation GROUP BY check_id, level, status"):
        d = by_check.setdefault(r["check_id"], {"level": r["level"]})
        d[r["status"]] = r["n"]
    failing = [dict(r) for r in store.q("SELECT exp_id, check_id, status, expected, actual, detail FROM validation"
                                        " WHERE status IN ('fail','warn') ORDER BY status, check_id, exp_id")]
    return {"by_check": by_check, "failing": failing}


def compute(cfg: PilotConfig, store: Store) -> dict:
    q = store.q
    exps = q("SELECT * FROM expediente")
    exp_channel = {e["id"]: e["channel"] for e in exps}

    stages = {r["stage"]: {"wall_s": r["wall_ms"] / 1000, "items": r["items"], "runs": r["runs"]}
              for r in q("SELECT stage, SUM(wall_ms) wall_ms, SUM(items) items, COUNT(*) runs FROM stage_run GROUP BY stage")}

    refs = q("SELECT d.*, b.bytes, b.ext, b.pages, b.text_chars, b.text_status FROM docref d LEFT JOIN blob b ON b.sha=d.sha")
    ref_status = Counter((r["source"], r["status"]) for r in refs)
    blobs = q("SELECT * FROM blob")
    first_exp = {}
    for r in q("SELECT sha, exp_id, role FROM docref WHERE sha IS NOT NULL ORDER BY id"):
        first_exp.setdefault(r["sha"], (r["exp_id"], r["role"]))

    by_role = defaultdict(lambda: Counter())
    for b in blobs:
        role = first_exp.get(b["sha"], (None, "?"))[1]
        c = by_role[role]
        c["files"] += 1
        c["bytes"] += b["bytes"] or 0
        c["pages"] += b["pages"] or 0
        c["chars"] += b["text_chars"] or 0
        c["text_ms"] += b["text_ms"] or 0
        c["summary_ms"] += b["summary_ms"] or 0
        c["ner_chunks_total"] += b["ner_chunks_total"] or 0
        c["ner_chunks_selected"] += b["ner_chunks_selected"] or 0
    by_ext = Counter()
    ext_bytes = Counter()
    for b in blobs:
        by_ext[b["ext"]] += 1
        ext_bytes[b["ext"]] += b["bytes"] or 0
    text_status = Counter(b["text_status"] for b in blobs)
    summary_status = Counter(b["summary_status"] for b in blobs)

    calls = [dict(r) for r in q(
        "SELECT service, task, COUNT(*) calls, SUM(ok) ok, SUM(input_chars) inp, SUM(output_chars) outp,"
        " SUM(wall_ms) wall, AVG(CASE WHEN ok=1 THEN wall_ms END) avg_ok FROM service_call GROUP BY service, task ORDER BY wall DESC")]
    calls_tot = dict(q("SELECT COUNT(*) calls, SUM(ok) ok, SUM(wall_ms) wall FROM service_call")[0])
    ch = q("SELECT COUNT(*) total, SUM(selected) selected, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) ok,"
           " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed, AVG(CASE WHEN status='ok' THEN ms END) avg_ms,"
           " SUM(entities) entities, SUM(relations) relations FROM chunk")[0]
    ner = dict(ch)
    # Time NER would take without the per-document chunk cap, at this run's mean time per chunk.
    ner["skipped"] = (ner["total"] or 0) - (ner["selected"] or 0)
    ner["extra_ms_without_cap"] = int((ner["avg_ms"] or 0) * ner["skipped"])
    desc = dict(q("SELECT COUNT(*) n, SUM(CASE WHEN kind='entity' THEN 1 ELSE 0 END) entities,"
                  " SUM(CASE WHEN kind='relation' THEN 1 ELSE 0 END) relations, SUM(ms) ms FROM description")[0])

    # Per-expediente work time: every item's own duration, each file counted once (on its first expediente).
    per = defaultdict(lambda: Counter())
    for e in exps:
        per[e["id"]]["detail_ms"] += e["detail_ms"] or 0
        per[e["id"]]["graph_ms"] += e["graph_ms"] or 0
    seen_url = set()
    for r in refs:
        p = per[r["exp_id"]]
        p["refs"] += 1
        if r["status"] == "fetched":
            p["docs"] += 1
        if r["url"] and r["url"] not in seen_url and r["fetch_ms"]:
            seen_url.add(r["url"])
            p["fetch_ms"] += r["fetch_ms"]
    for b in blobs:
        exp = first_exp.get(b["sha"], (None,))[0]
        if exp is None:
            continue
        p = per[exp]
        p["files"] += 1
        p["bytes"] += b["bytes"] or 0
        p["pages"] += b["pages"] or 0
        p["chars"] += b["text_chars"] or 0
        p["text_ms"] += b["text_ms"] or 0
        p["summary_ms"] += b["summary_ms"] or 0
    # NLP time per expediente: every service call is tagged with the expediente of its document.
    for x in q("SELECT exp_id, COUNT(*) n, SUM(wall_ms) ms, SUM(CASE WHEN task='ner' THEN wall_ms ELSE 0 END) ner_ms"
               " FROM service_call WHERE service='nlp' GROUP BY exp_id"):
        if x["exp_id"] in per:
            per[x["exp_id"]]["nlp_calls"] += x["n"]
            per[x["exp_id"]]["nlp_ms"] += x["ms"] or 0
            per[x["exp_id"]]["ner_ms"] += x["ner_ms"] or 0
    for eid, p in per.items():
        p["work_ms"] = sum(p[k] for k in ("detail_ms", "fetch_ms", "text_ms", "nlp_ms", "graph_ms"))

    by_channel = {}
    for ch in sorted(set(exp_channel.values())):
        ids = [i for i, c in exp_channel.items() if c == ch]
        by_channel[ch] = {k: _dist([per[i][k] for i in ids]) for k in
                          ("docs", "files", "bytes", "pages", "chars", "nlp_calls", "nlp_ms", "ner_ms", "work_ms",
                           "fetch_ms", "text_ms")}
        by_channel[ch]["expedientes"] = len(ids)

    disk = {name: _du(cfg.run_dir / name) for name in ("files", "text", "raw", "out")}
    disk["pilot.db"] = sum(os.path.getsize(p) for p in cfg.run_dir.glob("pilot.db*"))
    nodes = edges = 0
    labels = Counter()
    if (cfg.out_dir / "nodes.jsonl").exists():
        for line in (cfg.out_dir / "nodes.jsonl").open(encoding="utf-8"):
            nodes += 1
            labels[json.loads(line)["label"]] += 1
        edges = sum(1 for _ in (cfg.out_dir / "edges.jsonl").open(encoding="utf-8"))

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": platform.node(), "platform": platform.platform(),
        "config": {"nlp_url": cfg.nlp_url, "ocr": bool(cfg.ocr_url), "vectorizer": bool(cfg.vectorizer_url),
                   "chunk_words": cfg.chunk_words, "ner_max_chunks": cfg.ner_max_chunks,
                   "describe_relations": cfg.describe_relations, "fetch_workers": cfg.fetch_workers,
                   "nlp_workers": cfg.nlp_workers},
        "expedientes": {"total": len(exps), "by_channel": Counter(exp_channel.values()),
                        "analysable": sum(1 for e in exps if e["analysable"]),
                        "detail": Counter(e["detail_status"] for e in exps)},
        "stages": stages,
        "docrefs": {"total": len(refs), "by_source_status": {f"{s}/{st}": n for (s, st), n in sorted(ref_status.items())}},
        "files": {"unique": len(blobs), "bytes": sum(b["bytes"] or 0 for b in blobs),
                  "pages": sum(b["pages"] or 0 for b in blobs), "chars": sum(b["text_chars"] or 0 for b in blobs),
                  "text_status": text_status, "summary_status": summary_status,
                  "by_ext": {k: {"files": by_ext[k], "bytes": ext_bytes[k]} for k in by_ext},
                  "ocr_pages": sum(b["ocr_pages"] or 0 for b in blobs), "ocr_ms": sum(b["ocr_ms"] or 0 for b in blobs)},
        "by_role": {k: dict(v) for k, v in sorted(by_role.items(), key=lambda kv: -kv[1]["bytes"])},
        "service_calls": {"total": calls_tot, "by_task": calls},
        "ner": ner, "descriptions": desc,
        "by_channel": by_channel,
        "per_expediente": {eid: dict(p, channel=exp_channel.get(eid)) for eid, p in per.items()},
        "disk_bytes": disk,
        "graph": {"nodes": nodes, "edges": edges, "labels": labels},
        "index": _index_stats(store),
        "validation": _validation(store),
        "feed_updates_per_day": _feed_rate(cfg),
    }


def _fmt_s(ms) -> str:
    s = (ms or 0) / 1000
    return f"{s:.0f} s" if s < 120 else (f"{s / 60:.1f} min" if s < 7200 else f"{s / 3600:.1f} h")


def _mb(b) -> str:
    return f"{(b or 0) / MB:,.1f} MB"


def render(m: dict) -> str:
    L = []
    w = L.append
    w(f"# PLACSP pilot report\n\nGenerated {m['generated']} on `{m['host']}` ({m['platform']}).\n")
    c = m["config"]
    w(f"nlp_service at {c['nlp_url']}; OCR {'on' if c['ocr'] else 'off'}; embeddings {'on' if c['vectorizer'] else 'off'}; "
      f"NER chunks of {c['chunk_words']} words, at most {c['ner_max_chunks'] or 'all'} per document; relation descriptions "
      f"{'on' if c['describe_relations'] else 'off'}; {c['fetch_workers']} fetch / {c['nlp_workers']} NLP workers.\n")
    e = m["expedientes"]
    w(f"## Sample\n\n{e['total']} expedientes: " + ", ".join(f"{k} {v}" for k, v in sorted(e['by_channel'].items()))
      + f". {e['analysable']} analysable (the rest are menores/encargos, published already awarded).\n")

    w("## Wall time per stage\n\n| Stage | Wall time | Items |\n|---|---:|---:|")
    total = 0
    for s in ("select", "discover", "fetch", "text", "classify", "summarize", "ner", "resolve", "describe", "consolidate",
              "graph", "index", "validate"):
        if s in m["stages"]:
            st = m["stages"][s]
            total += st["wall_s"]
            w(f"| {s} | {_fmt_s(st['wall_s'] * 1000)} | {st['items']} |")
    w(f"| **total** | **{_fmt_s(total * 1000)}** | |\n")

    f = m["files"]
    w(f"## Volumes\n\n- Document references: {m['docrefs']['total']}; unique files downloaded: {f['unique']} "
      f"({_mb(f['bytes'])}, {f['pages']:,} PDF pages, {f['chars']:,} characters of text).")
    w("- Text extraction: " + ", ".join(f"{k} {v}" for k, v in f["text_status"].items())
      + (f"; OCR {f['ocr_pages']} pages in {_fmt_s(f['ocr_ms'])}" if f["ocr_pages"] else ""))
    w("- Disk: " + ", ".join(f"{k} {_mb(v)}" for k, v in m["disk_bytes"].items())
      + f"; total {_mb(sum(m['disk_bytes'].values()))}.")
    w(f"- Graph: {m['graph']['nodes']:,} nodes, {m['graph']['edges']:,} edges ("
      + ", ".join(f"{k} {v}" for k, v in sorted(m['graph']['labels'].items(), key=lambda kv: -kv[1])) + ").\n")

    w("### By document role\n\n| Role | Files | Size | Pages | Characters | NER chunks (processed / total) |\n|---|---:|---:|---:|---:|---:|")
    for role, v in m["by_role"].items():
        w(f"| {role} | {v.get('files', 0)} | {_mb(v.get('bytes'))} | {v.get('pages', 0):,} | {v.get('chars', 0):,} | "
          f"{v.get('ner_chunks_selected', 0):,} / {v.get('ner_chunks_total', 0):,} |")
    w("\n### By file type\n\n| Type | Files | Size |\n|---|---:|---:|")
    for k, v in sorted(m["files"]["by_ext"].items(), key=lambda kv: -kv[1]["bytes"]):
        w(f"| {k} | {v['files']} | {_mb(v['bytes'])} |")

    t, n, dsc = m["service_calls"]["total"], m["ner"], m["descriptions"]
    w(f"\n## nlp_service and other services\n\n{t['calls'] or 0} calls ({(t['calls'] or 0) - (t['ok'] or 0)} failed), "
      f"{_fmt_s(t['wall'])} of call time.")
    w(f"NER: {n['ok'] or 0:,} of {n['selected'] or 0:,} selected chunks done ({n['failed'] or 0} failed), "
      f"{n['entities'] or 0:,} entities and {n['relations'] or 0:,} relations extracted; mean {_fmt_s(n['avg_ms'])} per chunk. "
      f"{n['skipped']:,} chunks of {n['total'] or 0:,} were left out by the per-document cap; processing them would add about "
      f"{_fmt_s(n['extra_ms_without_cap'])} of call time.")
    w(f"Descriptions: {dsc['entities'] or 0:,} entities and {dsc['relations'] or 0:,} relations.\n")
    w("| Service | Task | Calls | Failed | Input chars | Time | Mean per successful call |\n|---|---|---:|---:|---:|---:|---:|")
    for r in m["service_calls"]["by_task"]:
        w(f"| {r['service']} | {r['task']} | {r['calls']} | {r['calls'] - (r['ok'] or 0)} | {(r['inp'] or 0):,} | "
          f"{_fmt_s(r['wall'])} | {_fmt_s(r['avg_ok'])} |")

    w("\n## Per expediente, by channel\n\nWork time is the sum of each item's own processing time (fetch, text, LLM...), "
      "which is what a single worker would spend; wall time is lower when stages run in parallel.\n")
    w("| Channel | N | Docs (median / p90 / max) | MB (median / p90 / max) | NLP calls (median / max) | Work time (median / p90 / max) |\n|---|---:|---|---|---|---|")
    for ch, d in m["by_channel"].items():
        dd, b, l, wt = d["docs"], d["bytes"], d["nlp_calls"], d["work_ms"]
        if not dd.get("n"):
            continue
        w(f"| {ch} | {d['expedientes']} | {dd['median']:.0f} / {dd['p90']:.0f} / {dd['max']:.0f} | "
          f"{b['median'] / MB:.1f} / {b['p90'] / MB:.1f} / {b['max'] / MB:.1f} | "
          f"{(l.get('median') or 0):.0f} / {(l.get('max') or 0):.0f} | "
          f"{_fmt_s(wt['median'])} / {_fmt_s(wt['p90'])} / {_fmt_s(wt['max'])} |")

    rate = m["feed_updates_per_day"]
    if rate:
        w("\n## Projection\n\nFeed updates per day are measured from the head pages downloaded for this run "
          "(an update is a new tender or a new notice on an existing one). Cost per update uses this run's mean work time "
          "and size per expediente for the channel, so it is an upper bound: an update to a known expediente only adds its new documents.\n")
        w("| Channel | Updates/day | Mean work time / exp | Work time / day | Mean MB / exp | Storage / day |\n|---|---:|---:|---:|---:|---:|")
        for ch, r in sorted(rate.items()):
            d = m["by_channel"].get(ch)
            if not d or not d["work_ms"].get("n"):
                continue
            wt, b = d["work_ms"]["mean"], d["bytes"]["mean"]
            w(f"| {ch} | {r} | {_fmt_s(wt)} | {_fmt_s(wt * r)} | {b / MB:.1f} | {_mb(b * r)} |")

    ix = m.get("index") or {}
    if ix.get("tenders"):
        w(f"\n## Index\n\nQdrant: {ix['tenders']} tender points (payload {_mb(ix['payload'])}, largest {ix['max_payload'] / 1024:.0f} KB), "
          f"{ix['chunks']:,} chunk points, {ix.get('entity_points', 0):,} entity points; vectors of {ix.get('dim')} dimensions, "
          f"{ix['embeddings_cached']:,} cached embeddings ({_mb(ix['embedding_bytes'])}). Neo4j: {ix.get('graph_nodes', 0) + ix.get('chunk_nodes', 0):,} "
          f"nodes ({ix.get('chunk_nodes', 0):,} chunks), {ix.get('graph_edges', 0):,} graph edges plus chunk links.\n")
    v = m.get("validation") or {}
    if v.get("by_check"):
        w("\n## Validation\n\nEvery expediente is checked from feed to stores (`out/validation.csv` has every row). "
          "fail = the pilot did not do its job; warn = the published data is incomplete.\n")
        w("| Check | Level | Pass | Warn | Fail | Skip |\n|---|---|---:|---:|---:|---:|")
        for cid, d in sorted(v["by_check"].items()):
            w(f"| {cid} | {d['level']} | {d.get('pass', 0)} | {d.get('warn', 0)} | {d.get('fail', 0)} | {d.get('skip', 0)} |")
        fails = [f for f in v["failing"] if f["status"] == "fail"]
        if fails:
            w("\n**Failures**\n\n| Expediente | Check | Expected | Actual | Detail |\n|---|---|---|---|---|")
            for f in fails[:60]:
                w(f"| {f['exp_id']} | {f['check_id']} | {f['expected']} | {f['actual']} | {(f['detail'] or '')[:120]} |")

    w("\n## Slowest expedientes\n\n| Expediente | Channel | Docs | MB | Characters | NLP calls | Work time |\n|---|---|---:|---:|---:|---:|---:|")
    for eid, p in sorted(m["per_expediente"].items(), key=lambda kv: -kv[1].get("work_ms", 0))[:15]:
        w(f"| {eid} | {p.get('channel')} | {p.get('docs', 0)} | {(p.get('bytes', 0)) / MB:.1f} | {p.get('chars', 0):,} | "
          f"{p.get('nlp_calls', 0)} | {_fmt_s(p.get('work_ms'))} |")
    return "\n".join(L) + "\n"


def write(cfg: PilotConfig, store: Store) -> Path:
    m = compute(cfg, store)
    (cfg.out_dir / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    path = cfg.out_dir / "report.md"
    path.write_text(render(m), encoding="utf-8")
    return path
