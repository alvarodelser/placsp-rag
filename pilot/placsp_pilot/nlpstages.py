"""Document-level NLP stages, all through nlp_service on the server.

  classify    /nli                       zero-shot role for documents the rules could not label
  summarize   /summarize article         one gist per document (headline + 2-4 sentences)
  ner         /ner per ~512-word chunk   entities + relations of the procurement ontology
  summary     /summarize aggregate       the expediente's description, from its document gists
                                         in lifecycle order

What happens to the NER output (mentions, resolution, refinement, descriptions) is in
entities.py. Coreference is not run: nlp_service only exposes it in-process, not over HTTP.
"""
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from placsp_pilot import classify as C
from placsp_pilot import ontology
from placsp_pilot.config import PilotConfig
from placsp_pilot.order import order_documents
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


PAGE = re.compile(r"\[Página (\d+)\]")


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

# ── notices summarised from the feed (no model) ──────────────────────

NOTICE_ROLES = {C.TENDER_NOTICE, C.PRIOR_NOTICE, C.AWARD_NOTICE, C.FORMALIZATION_NOTICE, C.MODIFICATION_NOTICE}


def _eur(v) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €" if isinstance(v, (int, float)) else ""


_ES_LIST = {"result": "TenderResultCode", "contract_type": "ContractCode", "procedure": "SyndicationTenderingProcessCode"}


def notice_summary(role: str, t: dict, cl=None) -> dict:
    """A notice is the feed rendered as a page: its gist is written from the feed record. `cl`
    (Codelists) gives codes their Spanish names."""
    tender = t.get("tender") or {}
    name = tender.get("name") or t.get("atom_title") or ""
    auth = (t.get("authority") or {}).get("name") or ""

    def lab(d, kind=None):
        if not d:
            return ""
        return (cl.spanish(_ES_LIST[kind], d.get("code")) if cl and kind else None) or d.get("label") or ""
    lots = [l for l in t.get("lots") or [] if not l.get("implicit")]
    if role == C.AWARD_NOTICE:
        parts = []
        for r in t.get("results") or []:
            who = ", ".join(w["name"] for w in r.get("winners") or [] if w.get("name"))
            parts.append(" ".join(x for x in [
                f"Lote {', '.join(r['lots'])}:" if r.get("lots") and lots else "",
                lab(r.get("result"), "result") or "Adjudicado", f"a {who}" if who else "",
                f"por {_eur(r['amount_tax_excl'])} sin IVA" if r.get("amount_tax_excl") else "",
                f"({int(r['bids_received'])} ofertas)" if r.get("bids_received") is not None else ""] if x))
        return {"headline": f"Adjudicación: {name}"[:160], "summary": f"{auth}. " + "; ".join(parts) + ".", "source": "feed"}
    if role == C.FORMALIZATION_NOTICE:
        cs = [f"contrato {c['id']} firmado el {c['signed']}" if c.get("signed") else f"contrato {c['id']}"
              for r in t.get("results") or [] for c in r.get("contracts") or [] if c.get("id")]
        return {"headline": f"Formalización: {name}"[:160], "summary": f"{auth}. " + ("; ".join(cs) or "Contrato formalizado") + ".",
                "source": "feed"}
    if role == C.MODIFICATION_NOTICE:
        ms = [" ".join(x for x in [f"Modificación {m.get('id') or ''}".strip(),
                                    f"de {_eur(m['amount_change'])}" if m.get("amount_change") else "",
                                    f"(nuevo importe {_eur(m['final_amount'])})" if m.get("final_amount") else ""] if x)
              for m in t.get("modifications") or []]
        return {"headline": f"Modificación: {name}"[:160], "summary": f"{auth}. " + ("; ".join(ms) or "Modificación del contrato") + ".",
                "source": "feed"}
    kind = "Anuncio previo" if role == C.PRIOR_NOTICE else "Licitación"
    crit = t.get("award_criteria") or []
    deadline = (tender.get("deadline") or {}).get("date")
    ctype, proc = lab(tender.get("contract_type"), "contract_type"), lab(tender.get("procedure"), "procedure").lower()
    bits = [" por procedimiento ".join(x for x in (ctype, proc) if x),
            f"presupuesto {_eur(tender['budget_tax_excl'])} sin IVA" if tender.get("budget_tax_excl") else "",
            f"{len(lots)} lotes" if lots else "", f"plazo de ofertas hasta {deadline}" if deadline else "",
            f"{len(crit)} criterios de adjudicación" if crit else ""]
    return {"headline": f"{kind}: {name}"[:160], "summary": f"{auth}. " + ", ".join(b for b in bits if b) + ".", "source": "feed"}


def feed_summaries(cfg: PilotConfig, store: Store) -> int:
    """Summaries of the notices, from their expediente's feed record; `summarize` leaves them."""
    n = 0
    from placsp_pilot.codelists import Codelists
    cl = Codelists(cfg.codelist_dir)
    rows = store.q("SELECT b.sha, d.role, e.tender_json FROM blob b JOIN docref d ON d.sha=b.sha JOIN expediente e ON e.id=d.exp_id"
                   " WHERE b.summary_status='pending' AND b.text_status='ok' AND d.role IN (%s) GROUP BY b.sha"
                   % ",".join("?" * len(NOTICE_ROLES)), sorted(NOTICE_ROLES))
    for r in rows:
        store.update("blob", {"sha": r["sha"]}, summary_status="ok", summary_ms=0,
                     summary_json=notice_summary(r["role"], json.loads(r["tender_json"]), cl))
        n += 1
    log(f"summaries from the feed: {n} notices")
    return n


def summarize(cfg: PilotConfig, store: Store, max_doc_chars: int):
    feed_summaries(cfg, store)
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

    def save(b, status, out, ms):
        store.update("blob", {"sha": b["sha"]}, summary_status=status, summary_json=out, summary_ms=ms)

    # Preflight: if the first document fails after its retries, the rest would too (a 503 means
    # nlp_service is up but its model is not): stop instead of failing every document.
    if blobs:
        b, status, out, ms = one(blobs[0])
        save(b, status, out, ms)
        if status != "ok":
            raise SystemExit(f"summarize: /summarize failed, last error: {out['error']}")
        blobs = blobs[1:]

    failed = 0
    with store.stage("summarize") as st, _pool(cfg.nlp_workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(one, b) for b in blobs]), 1):
            b, status, out, ms = f.result()
            save(b, status, out, ms)
            st["items"] += 1
            failed += status == "failed"
            if i % 20 == 0 or i == len(blobs):
                log(f"summarize {i}/{len(blobs)}, {failed} failed" + (f" (last: {out['error'][-200:]})" if status == "failed" else ""))


# ── ner ───────────────────────────────────────────────────────────────────

# A feed requirement that only points at the pliego ("según cláusula 8ª PCAP") says nothing itself.
REFERENCE_ONLY = re.compile(r"(cl[aá]usula|pliego|pcap|anexo|apartado|seg[uú]n|de acuerdo|conforme|ver\b)", re.I)


def reference_only(text: str | None, amount=None) -> bool:
    """A pointer and little else: "Según cláusula 8ª PCAP", not "Título-licencia de agencias de
    viajes otorgado por la Administración competente, según…", which is a requirement itself."""
    from placsp_pilot.lexical import terms
    text = text or ""
    return amount is None and len(text) < 160 and bool(REFERENCE_ONLY.search(text)) and len(terms(text)) <= 9


def single_bid(tender_json: dict) -> bool:
    """Every result of the expediente says one bid was received (or none): its only bidder is the
    feed's winner."""
    results = tender_json.get("results") or []
    return bool(results) and all(r.get("bids_received") is not None and r["bids_received"] <= 1 for r in results)


def feed_lacks(tender_json: dict) -> set[str]:
    """The feed types this expediente's feed does not give, so NER looks for them in the pliegos;
    and "single_bid" when the feed settles the competition (see single_bid)."""
    out = {"single_bid"} if single_bid(tender_json) else set()
    if not tender_json.get("award_criteria"):
        out.add("AWARD_CRITERION")
    reqs = [r for r in tender_json.get("requirements") or [] if r.get("group") != "declaration"]
    if not reqs or all(reference_only(r.get("text"), r.get("threshold")) for r in reqs):
        out.add("REQUIREMENT")
    if not tender_json.get("guarantees"):
        out.add("GUARANTEE")
    return out


class Schemas:
    """The /ner schema of each document: by its role, and by what its expediente's feed lacks."""

    def __init__(self, cfg: PilotConfig, store: Store):
        self.data = ontology.load(cfg.ontology_path)
        self.store = store
        self._lacks: dict[str, set] = {}
        self._cache: dict[tuple, dict | None] = {}

    def types(self, sha: str) -> set[str]:
        ref = _ref(self.store, sha)
        if not ref:
            return set()
        if ref["exp_id"] not in self._lacks:
            e = self.store.one("SELECT tender_json FROM expediente WHERE id=?", (ref["exp_id"],))
            self._lacks[ref["exp_id"]] = feed_lacks(json.loads(e["tender_json"])) if e else set()
        return ontology.ner_types(self.data, ref["role"], self._lacks[ref["exp_id"]])

    def schema(self, sha: str) -> dict | None:
        key = frozenset(self.types(sha))
        if key not in self._cache:
            self._cache[key] = ontology.extraction_schema_for(self.data, set(key)) if key else None
        return self._cache[key]


def _plan_chunks(cfg: PilotConfig, store: Store, schemas: Schemas):
    """Create chunk rows for documents not yet chunked and mark which ones NER will process.
    A document whose role no profile reads is chunked (for retrieval and provenance) but skipped."""
    skip_roles = {r.strip() for r in cfg.ner_skip_roles.split(",") if r.strip()}
    from placsp_pilot.sections import document
    for b in store.q("SELECT sha, text_path, chunker FROM blob WHERE ner_status='pending' AND text_status='ok'"
                     " AND sha NOT IN (SELECT DISTINCT sha FROM chunk)"):
        ref = _ref(store, b["sha"])
        text = Path(b["text_path"]).read_text(encoding="utf-8")
        pieces, paths, _ = document(b["text_path"], cfg.chunk_words, b["chunker"])
        scores = [_score(p) for p in pieces]
        keep = set(range(len(pieces)))
        # Every document is chunked, whether or not NER reads it: chunks are what retrieval and
        # provenance point at.
        if not ref or ref["role"] in skip_roles or not schemas.types(b["sha"]):
            keep = set()
            store.update("blob", {"sha": b["sha"]}, ner_status="skipped")
        elif ref["role"] in (C.PCAP, C.PCAP_PPT) and cfg.ner_by_section:
            # A pliego administrativo is read only in the sections that hold what NER looks for in it.
            from placsp_pilot.locate import relevant_chunks
            sections = relevant_chunks(text, cfg.chunk_words, schemas.types(b["sha"]), chunker=b["chunker"],
                                       text_path=b["text_path"])
            if sections is not None:
                keep = sections
        if keep and cfg.ner_max_chunks and len(keep) > cfg.ner_max_chunks:
            ranked = sorted(keep, key=lambda i: (-scores[i], i))
            keep = set(ranked[:cfg.ner_max_chunks])
        with store.tx() as c:
            c.executemany(
                "INSERT OR IGNORE INTO chunk (sha, idx, words, chars, score, selected, status, section) VALUES (?,?,?,?,?,?,?,?)",
                [(b["sha"], i, len(p.split()), len(p), scores[i], int(i in keep), "pending" if i in keep else "skipped",
                  " › ".join(paths[i]) or None) for i, p in enumerate(pieces)])
        store.update("blob", {"sha": b["sha"]}, ner_chunks_total=len(pieces), ner_chunks_selected=len(keep))


def ner(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    schemas = Schemas(cfg, store)
    _plan_chunks(cfg, store, schemas)
    from placsp_pilot.sections import document, without_furniture
    rows = store.q("SELECT c.sha, c.idx, c.section, b.text_path, b.chunker FROM chunk c JOIN blob b ON b.sha=c.sha"
                   " WHERE c.status='pending' ORDER BY c.sha, c.idx")

    def piece(r) -> str:
        """What NER reads: the chunk without its page furniture, headed by the section it is in.
        Quotes NER returns are located in the stored chunk, which keeps both."""
        chunks, _, furniture = document(r["text_path"], cfg.chunk_words, r["chunker"])
        body = without_furniture(chunks[r["idx"]], furniture)
        return f"[Sección: {r['section']}]\n{body}" if r["section"] else body

    def one(r):
        t0 = time.time()
        ref = _ref(store, r["sha"])
        try:
            out = svc.ner(piece(r), schemas.schema(r["sha"]),
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
        log(f"ner preflight: {status} in {ms / 1000:.0f}s {out.get('error', '')}")
    else:
        if rows and status != "ok":
            raise SystemExit(f"ner: /ner failed twice, last error: {out.get('error')}")
        if rows:
            raise SystemExit(f"ner: one /ner call took {ms / 1000:.0f}s, over PILOT_NER_PREFLIGHT_S="
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
        c.execute("UPDATE blob SET ner_status='ok' WHERE ner_status='pending' AND text_status='ok'"
                  " AND sha NOT IN (SELECT sha FROM chunk)")


# ── summary (one description per expediente) ──────────────────────────

ROLE_ORDER = {r: i for i, r in enumerate(C.ROLES)}
MAX_AGG_DESCRIPTIONS = 30
MAX_AGG_ENTITIES = 20
SUMMARY_TYPES = ("COMPANY", "JOINT_VENTURE", "AWARD_CRITERION", "REQUIREMENT", "GUARANTEE", "PENALTY", "CONTRACT",
                 "MODIFICATION", "TEAM_PROFILE")


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


def summary(cfg: PilotConfig, store: Store):
    svc = Services(cfg, store)
    done = {r["exp_id"] for r in store.q("SELECT exp_id FROM extraction WHERE kind='tender_description' AND status='ok'")}
    jobs = []
    for e in store.q("SELECT id, title, tender_json FROM expediente"):
        if e["id"] in done:
            continue
        tender = json.loads(e["tender_json"])
        docs = [dict(d) for d in store.q(
            "SELECT d.sha, d.role, d.label, MIN(d.published) published, MAX(d.notice_type) notice_type, b.summary_json"
            " FROM docref d JOIN blob b ON b.sha=d.sha WHERE d.exp_id=? AND b.summary_status='ok' GROUP BY d.sha", (e["id"],))]
        # Over the cap, the most informative roles are kept; either way the model reads the
        # documents in lifecycle order, each introduced by its position, role and date.
        keep = {d["sha"] for d in sorted(docs, key=lambda d: ROLE_ORDER.get(d["role"], 99))[:MAX_AGG_DESCRIPTIONS]}
        descriptions = []
        for d in order_documents(docs, tender):
            if d["sha"] in keep:
                s = json.loads(d["summary_json"])
                descriptions.append(f"[Documento {d['seq']} · {d['role']} · {d['effective_date'] or 'sin fecha'}] "
                                    f"{s.get('headline', '')}: {s.get('summary', '')}")
        # And what is known about its entities, gathered from every mention in every document.
        for x in store.q(
                "SELECT e.type, e.name, d.text FROM entity e JOIN entity_description d ON d.item_id=e.id AND d.kind='entity'"
                " AND d.exp_id IN (e.exp_id, '*') AND d.status='ok' WHERE e.exp_id=? AND e.type IN (%s)"
                " ORDER BY e.mentions DESC" % ",".join("?" * len(SUMMARY_TYPES)), (e["id"], *SUMMARY_TYPES))[:MAX_AGG_ENTITIES]:
            descriptions.append(f"[Entidad · {x['type']}] {x['name']}: {x['text']}")
        evidence = [l for l in facts_brief(tender).split("\n") if l.split(":", 1)[-1].strip()]
        jobs.append((e["id"], {"name": e["title"] or e["id"], "type": "Expediente de contratación pública",
                               "descriptions": descriptions or ["(sin documentos)"], "evidence": evidence}))

    def one(job):
        exp_id, fields = job
        t0 = time.time()
        try:
            return exp_id, "ok", svc.summarize("aggregate", fields, exp_id=exp_id), int((time.time() - t0) * 1000)
        except ServiceError as err:
            return exp_id, "failed", {"error": str(err)}, int((time.time() - t0) * 1000)

    with store.stage("summary") as st, _pool(cfg.nlp_workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            exp_id, status, out, ms = f.result()
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO extraction (exp_id, kind, sha, status, result_json, ms) VALUES (?,?,?,?,?,?)",
                          (exp_id, "tender_description", "-", status, json.dumps(out, ensure_ascii=False), ms))
            st["items"] += 1
        log(f"summary: {st['items']} expediente descriptions")
    titles(cfg, store, svc)


TITLE_WORDS = 14     # a name longer than this gets a short title written for it


def short_name(name: str) -> str:
    """The name without its translation: "Obra X / Obra X" (Valencian, Catalan, Galician, Basque) keeps the first."""
    parts = [p.strip() for p in re.split(r"\s+/\s+", name or "") if p.strip()]
    return parts[0] if len(parts) == 2 else (name or "").strip()


def titles(cfg: PilotConfig, store: Store, svc: "Services"):
    """A short title per expediente (the article profile's 8-15 word headline) when its name is long;
    otherwise the name itself, without a call."""
    done = {r["exp_id"] for r in store.q("SELECT exp_id FROM extraction WHERE kind='tender_title' AND status='ok'")}
    jobs = []
    with store.tx() as c:
        for e in store.q("SELECT id, title, tender_json FROM expediente"):
            if e["id"] in done:
                continue
            name = (json.loads(e["tender_json"]).get("tender") or {}).get("name") or e["title"] or ""
            short = short_name(name)
            if len(short.split()) <= TITLE_WORDS:
                c.execute("INSERT OR REPLACE INTO extraction (exp_id, kind, sha, status, result_json, ms) VALUES (?,?,?,?,?,?)",
                          (e["id"], "tender_title", "-", "ok", json.dumps({"title": short, "how": "name"}, ensure_ascii=False), 0))
            else:
                desc = store.one("SELECT result_json FROM extraction WHERE exp_id=? AND kind='tender_description' AND status='ok'", (e["id"],))
                jobs.append((e["id"], short, json.loads(desc["result_json"]).get("description") if desc else ""))

    def one(job):
        exp_id, name, desc = job
        t0 = time.time()
        try:
            out = svc.summarize("article", {"title": name, "text": f"{name}\n\n{desc or ''}"}, exp_id=exp_id)
            return exp_id, "ok", {"title": out.get("headline") or name, "how": "llm"}, int((time.time() - t0) * 1000)
        except ServiceError as err:
            return exp_id, "failed", {"error": str(err)}, int((time.time() - t0) * 1000)

    with store.stage("titles") as st, _pool(cfg.nlp_workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            exp_id, status, out, ms = f.result()
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO extraction (exp_id, kind, sha, status, result_json, ms) VALUES (?,?,?,?,?,?)",
                          (exp_id, "tender_title", "-", status, json.dumps(out, ensure_ascii=False), ms))
            st["items"] += 1
    if jobs:
        log(f"summary: {len(jobs)} short titles for long names")
