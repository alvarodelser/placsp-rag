"""NLP stages, all through nlp_service on the server.

The sequence is Phase A of nlp_service's relation pipeline (pipelines/relations/orchestrator.py),
run per document over HTTP and kept in pilot.db instead of the shared Weaviate:

  classify    /nli                       zero-shot role for documents the rules could not label
  summarize   /summarize article         one gist per document (headline + 2-4 sentences)
  ner         /ner per ~512-word chunk   entities + relations of the procurement ontology
  resolve     /resolve per document      mentions -> canonical entities, relations re-pointed
  describe    /summarize entity_desc and relation_desc   one GraphRAG description each
  consolidate /summarize aggregate       expediente description; companies seen in several docs

Coreference is not run: nlp_service only exposes it in-process, not over HTTP.
"""
import json
import re
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from placsp_pilot import classify as C
from placsp_pilot import ontology
from placsp_pilot.config import PilotConfig
from placsp_pilot.services import ServiceError, Services
from placsp_pilot.store import Store


def log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


# Vocabulary of the ontology's concepts, used to rank chunks when a document is over the cap.
PROCUREMENT_KW = [_fold(k) for k in [
    "criterio", "puntuacion", "puntos", "ponderacion", "formula", "juicio de valor", "sobre",
    "solvencia", "volumen de negocios", "seguro", "clasificacion", "grupo", "subgrupo", "experiencia",
    "titulacion", "certificad", "garantia", "penalidad", "plazo", "lote", "licitador", "oferta",
    "adjudica", "excluid", "admitid", "precio", "importe", "nif", "ute", "contrato", "prorroga",
    "modificacion", "entregable", "perfil", "equipo", "nivel de servicio", "requisito", "subcontrat",
    "criteris", "solvencia", "licitadora", "adjudicataria", "irizpide", "kaudimen", "eskaintza"]]


def split_words(text: str, max_words: int) -> list[str]:
    """Paragraph-aware word-budget splitter, as nlp_service's pipelines/relations/chunker.py."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur, cur_words = [], [], 0
    for p in paragraphs:
        n = len(p.split())
        if n > max_words:
            if cur:
                chunks.append("\n\n".join(cur))
                cur, cur_words = [], 0
            words = p.split()
            chunks.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
            continue
        if cur_words + n > max_words and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_words = [], 0
        cur.append(p)
        cur_words += n
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def _score(chunk: str) -> int:
    f = _fold(chunk)
    return sum(f.count(k) for k in PROCUREMENT_KW)


def _ref(store: Store, sha: str):
    return store.one(
        "SELECT d.exp_id, d.label, d.role, e.title FROM docref d JOIN expediente e ON e.id=d.exp_id"
        " WHERE d.sha=? ORDER BY d.id LIMIT 1", (sha,))


def _pool(n: int):
    return ThreadPoolExecutor(max(1, n))


# ── classify ──────────────────────────────────────────────────────────────

NLI_MIN_SCORE = 0.5


def classify(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    rows = store.q("SELECT d.sha, MIN(d.label) label, MIN(d.exp_id) exp_id, b.text_path FROM docref d"
                   " JOIN blob b ON b.sha=d.sha WHERE b.text_status='ok' AND d.role_source IN (%s)"
                   " GROUP BY d.sha" % ",".join("?" * len(C.WEAK_SOURCES)), C.WEAK_SOURCES)
    roles, hyps = zip(*C.NLI_HYPOTHESES.items())

    def one(r):
        head = Path(r["text_path"]).read_text(encoding="utf-8")[:1500]
        try:
            scores = svc.nli(f"{r['label']}\n{head}", list(hyps), "Este documento es {}.", exp_id=r["exp_id"], sha=r["sha"])
        except ServiceError:
            return r, None, 0.0
        best = max(range(len(scores)), key=lambda i: scores[i]["score"])
        return r, roles[best], scores[best]["score"]

    with store.stage("classify") as st, _pool(cfg.nlp_workers) as pool:
        for f in as_completed([pool.submit(one, r) for r in rows]):
            r, role, score = f.result()
            if role and score >= NLI_MIN_SCORE:
                with store.tx() as c:
                    c.execute("UPDATE docref SET role=?, role_source=? WHERE sha=? AND role_source IN (%s)"
                              % ",".join("?" * len(C.WEAK_SOURCES)), (role, f"nli:{score:.2f}", r["sha"], *C.WEAK_SOURCES))
                st["items"] += 1
        log(f"classify: {st['items']} of {len(rows)} unlabelled documents relabelled")


# ── summarize ─────────────────────────────────────────────────────────────

def summarize(cfg: PilotConfig, store: Store, max_doc_chars: int):
    svc = Services(cfg, store)
    blobs = store.q("SELECT sha, text_path, text_chars FROM blob WHERE summary_status='pending' AND text_status='ok'")

    def one(b):
        t0 = time.time()
        ref = _ref(store, b["sha"])
        text = Path(b["text_path"]).read_text(encoding="utf-8")[:max_doc_chars]
        try:
            # The service reduces long input extractively (TextRank) to its context budget.
            out = svc.summarize("article", {"title": ref["label"] if ref else "", "text": text},
                                exp_id=ref["exp_id"] if ref else None, sha=b["sha"])
            return b, "ok", out, int((time.time() - t0) * 1000)
        except ServiceError as e:
            return b, "failed", {"error": str(e)}, int((time.time() - t0) * 1000)

    with store.stage("summarize") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, b) for b in blobs]), 1):
            b, status, out, ms = f.result()
            store.update("blob", {"sha": b["sha"]}, summary_status=status, summary_json=out, summary_ms=ms)
            st["items"] += 1
            if i % 20 == 0 or i == len(blobs):
                log(f"summarize {i}/{len(blobs)}")


# ── ner ───────────────────────────────────────────────────────────────────

def _plan_chunks(cfg: PilotConfig, store: Store):
    """Create chunk rows for documents not yet chunked and mark which ones NER will process."""
    skip_roles = {r.strip() for r in cfg.ner_skip_roles.split(",") if r.strip()}
    for b in store.q("SELECT sha, text_path FROM blob WHERE ner_status='pending' AND text_status='ok'"
                     " AND sha NOT IN (SELECT DISTINCT sha FROM chunk)"):
        ref = _ref(store, b["sha"])
        if ref and ref["role"] in skip_roles:
            store.update("blob", {"sha": b["sha"]}, ner_status="skipped", resolve_status="skipped", describe_status="skipped")
            continue
        pieces = split_words(Path(b["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words)
        scores = [_score(p) for p in pieces]
        keep = set(range(len(pieces)))
        if cfg.ner_max_chunks and len(pieces) > cfg.ner_max_chunks:
            ranked = sorted(range(len(pieces)), key=lambda i: (-scores[i], i))
            keep = set(ranked[:cfg.ner_max_chunks])
        with store.tx() as c:
            c.executemany(
                "INSERT OR IGNORE INTO chunk (sha, idx, words, chars, score, selected, status) VALUES (?,?,?,?,?,?,?)",
                [(b["sha"], i, len(p.split()), len(p), scores[i], int(i in keep), "pending" if i in keep else "skipped")
                 for i, p in enumerate(pieces)])
        store.update("blob", {"sha": b["sha"]}, ner_chunks_total=len(pieces), ner_chunks_selected=len(keep))


def ner(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    schema = ontology.extraction_schema(ontology.load(cfg.ontology_path))
    _plan_chunks(cfg, store)
    rows = store.q("SELECT c.sha, c.idx, b.text_path FROM chunk c JOIN blob b ON b.sha=c.sha"
                   " WHERE c.status='pending' ORDER BY c.sha, c.idx")
    text_cache: dict[str, list[str]] = {}

    def piece(sha: str, path: str, idx: int) -> str:
        if sha not in text_cache:
            text_cache[sha] = split_words(Path(path).read_text(encoding="utf-8"), cfg.chunk_words)
        return text_cache[sha][idx]

    def one(r):
        t0 = time.time()
        ref = _ref(store, r["sha"])
        try:
            out = svc.ner(piece(r["sha"], r["text_path"], r["idx"]), schema,
                          exp_id=ref["exp_id"] if ref else None, sha=r["sha"])
            return r, "ok", out, int((time.time() - t0) * 1000)
        except ServiceError as e:
            return r, "failed", {"error": str(e)}, int((time.time() - t0) * 1000)

    def save(r, status, out, ms):
        with store.tx() as c:
            c.execute("UPDATE chunk SET status=?, ms=?, entities=?, relations=?, result_json=? WHERE sha=? AND idx=?",
                      (status, ms, len(out.get("entities", [])), len(out.get("relations", [])),
                       json.dumps(out, ensure_ascii=False), r["sha"], r["idx"]))

    # Preflight: the first call may include loading the model, so a slow one gets a second try.
    # Two slow calls in a row mean thousands of them would be too: stop before queueing the rest.
    for _ in range(min(2, len(rows))):
        r, status, out, ms = one(rows[0])
        save(r, status, out, ms)
        rows = rows[1:]
        if status == "ok" and ms <= cfg.ner_preflight_s * 1000:
            break
        log(f"ner preflight: {status} in {ms / 1000:.0f}s")
    else:
        if rows:
            raise SystemExit(f"ner: one /ner call took {ms / 1000:.0f}s ({status}), over PILOT_NER_PREFLIGHT_S="
                             f"{cfg.ner_preflight_s:.0f}. Check that Ollama runs on the GPU (`ollama ps`) "
                             "and that thinking is off (OLLAMA_THINK=false).")

    with store.stage("ner") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, r) for r in rows]), 1):
            save(*f.result())
            st["items"] += 1
            if i % 25 == 0 or i == len(rows):
                log(f"ner {i}/{len(rows)} chunks")
    for b in store.q("SELECT sha FROM blob WHERE ner_status='pending' AND sha IN (SELECT sha FROM chunk)"):
        counts = {r["status"]: r["n"] for r in store.q("SELECT status, COUNT(*) n FROM chunk WHERE sha=? GROUP BY status", (b["sha"],))}
        if counts.get("pending"):
            continue
        status = "failed" if counts.get("failed") and not counts.get("ok") else ("partial" if counts.get("failed") else "ok")
        store.update("blob", {"sha": b["sha"]}, ner_status=status)
    # Documents whose text splits into no chunk at all.
    with store.tx() as c:
        c.execute("UPDATE blob SET ner_status='ok', resolve_status='skipped', describe_status='skipped'"
                  " WHERE ner_status='pending' AND text_status='ok' AND sha NOT IN (SELECT sha FROM chunk)")


# ── resolve ───────────────────────────────────────────────────────────────

def flatten_chunks(chunk_results: list[dict]) -> tuple[list, list, list]:
    """As the relation pipeline: relation endpoint indices -> entity names; keep attribute records."""
    entities, relations, attrs = [], [], []
    for r in chunk_results:
        ents = r.get("entities", [])
        names = [e["name"] for e in ents]
        for e in ents:
            entities.append({"name": e["name"], "type": e["type"], "subtype": e.get("subtype"),
                             "evidence": e.get("evidence_text", "")})
            attrs.append({"name": e["name"], "type": e["type"], "attributes": e.get("attributes") or {},
                          "confidence": e.get("confidence", 0.0)})
        for rel in r.get("relations", []):
            if 0 <= rel["head"] < len(names) and 0 <= rel["tail"] < len(names):
                relations.append({"head": names[rel["head"]], "tail": names[rel["tail"]], "type": rel["type"],
                                  "subtype": rel.get("subtype"), "evidence": rel.get("evidence_text", ""),
                                  "attributes": rel.get("attributes") or {}, "confidence": rel.get("confidence", 0.0)})
    return entities, relations, attrs


def join_attributes(names: list[str], attrs: list[dict]) -> dict:
    """Highest-confidence non-null value per attribute across the entity's surface names."""
    recs = sorted((a for a in attrs if a["name"] in set(names)), key=lambda a: -float(a.get("confidence") or 0))
    out: dict = {}
    for a in recs:
        for k, v in a["attributes"].items():
            if v not in (None, "") and k not in out:
                out[k] = v
    return out


def resolve(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    blobs = store.q("SELECT sha FROM blob WHERE resolve_status='pending' AND ner_status IN ('ok','partial')")

    def one(b):
        t0 = time.time()
        results = [json.loads(r["result_json"]) for r in
                   store.q("SELECT result_json FROM chunk WHERE sha=? AND status='ok' ORDER BY idx", (b["sha"],))]
        entities, relations, attrs = flatten_chunks(results)
        if not entities:
            return b, "skipped", {"entities": [], "relations": [], "attrs": []}, 0
        ref = _ref(store, b["sha"])
        try:
            out = svc.resolve(entities, relations, exp_id=ref["exp_id"] if ref else None, sha=b["sha"])
            out["attrs"] = attrs
            return b, "ok", out, int((time.time() - t0) * 1000)
        except ServiceError as e:
            return b, "failed", {"error": str(e)}, int((time.time() - t0) * 1000)

    with store.stage("resolve") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, b) for b in blobs]), 1):
            b, status, out, ms = f.result()
            fields = dict(resolve_status=status, resolve_json=out, resolve_ms=ms)
            if status != "ok":
                fields["describe_status"] = "skipped"
            store.update("blob", {"sha": b["sha"]}, **fields)
            st["items"] += 1
            if i % 20 == 0 or i == len(blobs):
                log(f"resolve {i}/{len(blobs)}")


# ── describe ──────────────────────────────────────────────────────────────

def describe(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    jobs = []
    for b in store.q("SELECT sha, resolve_json FROM blob WHERE resolve_status='ok' AND describe_status='pending'"):
        res = json.loads(b["resolve_json"])
        names = {e["id"]: e["canonical_name"] for e in res.get("entities", [])}
        for e in res.get("entities", []):
            jobs.append((b["sha"], "entity", e["id"], "entity_desc", {
                "name": e["canonical_name"], "type": e["type"], "subtype": e.get("subtype"), "evidence": e["evidence"]}))
        if cfg.describe_relations:
            for k, r in enumerate(res.get("relations", [])):
                jobs.append((b["sha"], "relation", str(k), "relation_desc", {
                    "head": names.get(r["head_id"], r["head_id"]), "tail": names.get(r["tail_id"], r["tail_id"]),
                    "type": r["type"], "subtype": r.get("subtype"),
                    "attributes": json.dumps(r.get("attributes") or {}, ensure_ascii=False), "evidence": r["evidence"]}))
    done = {(r["sha"], r["kind"], r["item_id"]) for r in store.q("SELECT sha, kind, item_id FROM description WHERE status='ok'")}
    jobs = [j for j in jobs if (j[0], j[1], j[2]) not in done]
    exp_of = {}

    def one(job):
        sha, kind, item_id, profile, fields = job
        if sha not in exp_of:
            ref = _ref(store, sha)
            exp_of[sha] = ref["exp_id"] if ref else None
        t0 = time.time()
        try:
            out = svc.summarize(profile, fields, exp_id=exp_of[sha], sha=sha)
            return job, "ok", out.get("description"), int((time.time() - t0) * 1000)
        except ServiceError as e:
            return job, "failed", str(e), int((time.time() - t0) * 1000)

    with store.stage("describe") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, j) for j in jobs]), 1):
            (sha, kind, item_id, _, _), status, text, ms = f.result()
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO description (sha, kind, item_id, status, ms, text) VALUES (?,?,?,?,?,?)",
                          (sha, kind, item_id, status, ms, text))
            st["items"] += 1
            if i % 50 == 0 or i == len(jobs):
                log(f"describe {i}/{len(jobs)}")
    for b in store.q("SELECT sha FROM blob WHERE resolve_status='ok' AND describe_status='pending'"):
        failed = store.one("SELECT COUNT(*) n FROM description WHERE sha=? AND status!='ok'", (b["sha"],))["n"]
        store.update("blob", {"sha": b["sha"]}, describe_status="partial" if failed else "ok")


# ── consolidate (per expediente, and companies across expedientes) ───────

ROLE_ORDER = {r: i for i, r in enumerate(C.ROLES)}
MAX_AGG_DESCRIPTIONS = 30


def facts_brief(t: dict) -> str:
    """The feed facts of an expediente as short lines (no URLs, no document lists)."""
    tender = t.get("tender", {})
    lines = [
        f"Tipo: {(tender.get('contract_type') or {}).get('label')} / {(tender.get('subtype') or {}).get('label')}",
        f"Procedimiento: {(tender.get('procedure') or {}).get('label')}; SARA: {tender.get('sara')}",
        f"Estado: {(t.get('status') or {}).get('label')}",
        f"Órgano de contratación: {(t.get('authority') or {}).get('name')}",
        f"Valor estimado: {tender.get('value_estimated')}; presupuesto sin IVA: {tender.get('budget_tax_excl')}",
        f"CPV: {', '.join(tender.get('cpv') or [])}; lugar: {(tender.get('location') or {}).get('nuts')}",
        f"Plazo de presentación: {(tender.get('deadline') or {}).get('date')}",
        f"Duración: {(tender.get('duration') or {}).get('value')} {(tender.get('duration') or {}).get('unit')}",
        "Lotes: " + "; ".join(f"{l['number']} {l.get('name') or ''} ({l.get('budget_tax_excl')} €)" for l in t.get("lots", [])),
        "Criterios: " + "; ".join(f"[{c.get('lot') or '*'}] {c['name']} {c.get('points')} ({c.get('kind')})" for c in t.get("award_criteria", [])),
        "Solvencia: " + "; ".join(f"{(r.get('type') or {}).get('label') or r['group']}: {r.get('text')}"
                                  for r in t.get("requirements", []) if r["group"] in ("financial", "technical", "classification")),
        "Anuncios: " + "; ".join(f"{(n.get('type') or {}).get('label')} {n.get('published')}" for n in t.get("notices", [])),
    ]
    for res in t.get("results", []):
        lines.append(f"Resultado lotes {res['lots'] or ['1']}: {(res.get('result') or {}).get('label')} {res.get('award_date')};"
                     f" ofertas {res.get('bids_received')}; adjudicatarios {[w['name'] for w in res['winners']]};"
                     f" importe {res.get('amount_tax_excl')}")
    for m in t.get("modifications", []):
        lines.append(f"Modificación {m['id']}: {m.get('amount_change')} € -> {m.get('final_amount')} €; {(m.get('note') or '')[:200]}")
    return "\n".join(lines)


def consolidate(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    done = {(r["exp_id"], r["kind"], r["sha"]) for r in store.q("SELECT exp_id, kind, sha FROM extraction WHERE status='ok'")}
    jobs = []
    for e in store.q("SELECT id, title, tender_json FROM expediente"):
        if (e["id"], "tender_description", "-") in done:
            continue
        docs = store.q("SELECT d.role, d.label, b.summary_json FROM docref d JOIN blob b ON b.sha=d.sha"
                       " WHERE d.exp_id=? AND b.summary_status='ok' GROUP BY d.sha", (e["id"],))
        docs = sorted(docs, key=lambda d: ROLE_ORDER.get(d["role"], 99))[:MAX_AGG_DESCRIPTIONS]
        descriptions = []
        for d in docs:
            s = json.loads(d["summary_json"])
            descriptions.append(f"[{d['role']}] {s.get('headline', '')}: {s.get('summary', '')}")
        evidence = [l for l in facts_brief(json.loads(e["tender_json"])).split("\n") if l.split(":", 1)[-1].strip()]
        jobs.append((e["id"], "tender_description", "-", {
            "name": e["title"] or e["id"], "type": "Expediente de contratación pública",
            "descriptions": descriptions or ["(sin documentos)"], "evidence": evidence}))

    # Companies (by NIF, else normalised name) described in more than one document.
    from placsp_pilot.graph import org_id  # local import: graph imports this module's helpers
    org_descs: dict[str, dict] = defaultdict(lambda: {"names": set(), "descs": [], "evidence": []})
    for b in store.q("SELECT sha, resolve_json FROM blob WHERE resolve_status='ok'"):
        res = json.loads(b["resolve_json"])
        attrs = res.get("attrs", [])
        descs = {r["item_id"]: r["text"] for r in
                 store.q("SELECT item_id, text FROM description WHERE sha=? AND kind='entity' AND status='ok'", (b["sha"],))}
        for ent in res.get("entities", []):
            if ent["type"] not in ("COMPANY", "JOINT_VENTURE"):
                continue
            nif = join_attributes(ent["names"], attrs).get("nif")
            o = org_descs[org_id(ent["canonical_name"], nif)]
            o["names"].add(ent["canonical_name"])
            if descs.get(ent["id"]):
                o["descs"].append(descs[ent["id"]])
            o["evidence"].extend(ent["evidence"][:3])
    for oid, o in org_descs.items():
        if len(o["descs"]) > 1 and ("*", "org_description", oid) not in done:
            jobs.append(("*", "org_description", oid, {
                "name": sorted(o["names"], key=len)[-1], "type": "Empresa",
                "descriptions": o["descs"][:MAX_AGG_DESCRIPTIONS], "evidence": o["evidence"][:40]}))

    def one(job):
        exp_id, kind, key, fields = job
        t0 = time.time()
        try:
            out = svc.summarize("aggregate", fields, exp_id=None if exp_id == "*" else exp_id)
            return job, "ok", out, int((time.time() - t0) * 1000)
        except ServiceError as err:
            return job, "failed", {"error": str(err)}, int((time.time() - t0) * 1000)

    with store.stage("consolidate") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, j) for j in jobs]), 1):
            (exp_id, kind, key, _), status, out, ms = f.result()
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO extraction (exp_id, kind, sha, status, result_json, ms) VALUES (?,?,?,?,?,?)",
                          (exp_id, kind, key, status, json.dumps(out, ensure_ascii=False), ms))
            st["items"] += 1
        log(f"consolidate: {st['items']} descriptions")
