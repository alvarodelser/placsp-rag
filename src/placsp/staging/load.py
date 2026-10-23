"""current/ -> the search index (Weaviate) and the company graph (Neo4j).

Each tender becomes the ProcurementRecord the search app has always read (same properties, same
Spanish summary, same object id), plus a Placsp_pliego_criteria object with the platform criteria
(criteria_json: award criteria, guarantees, solvency, conditions, document links) that the pliegos
modal reads — built from the feed's structured terms.

Only tenders that changed since they were last loaded are loaded again: loaded.duckdb keeps a
fingerprint per tender (its latest update, its removal marker and LOAD_VERSION). Bump LOAD_VERSION
when the mapping changes and every tender is reloaded.
"""
import datetime
import json
import os
import time
import uuid

import duckdb
import structlog

from placsp.core.models import Lot, LotResult, ProcurementRecord, StatusEvent
from placsp.parsers.renderer import render

log = structlog.get_logger(service="placsp")

LOAD_VERSION = "1"
CHUNK = 2000
CRITERIA_CLASS = "Placsp_pliego_criteria"
CHILDREN = ("lot", "result", "winner", "criterion", "requirement", "guarantee", "condition", "notice",
            "document", "status_history")
# Codelist of each coded column (the list name in the codelist table: the .gc file without its version).
LISTS = {"status": "SyndicationContractFolderStatusCode", "contract_type": "ContractCode",
         "procedure": "SyndicationTenderingProcessCode", "result": "TenderResultCode", "nuts": "NUTS",
         "country": "CountryIdentificationCode", "OBJ": "AwardingCriteriaAutomaticallyEvaluatedSubTypeCode",
         "SUBJ": "AwardingCriteriaNotAutomaticallyEvaluatedSubTypeCode", "declaration": "DeclarationTypeCode",
         "financial": "FinancialCapabilityTypeCode", "technical": "TechnicalCapabilityTypeCode",
         "condition": "ExecutionRequirementCode"}
_UNITS = {"DAY": "días", "WEE": "semanas", "MON": "meses", "ANN": "años"}
_DOC_NAMES = {"legal": "Pliego de cláusulas administrativas (PCAP)",
              "technical": "Pliego de prescripciones técnicas (PPT)", "additional": "Documento adicional"}


def fetch_dicts(con, sql: str, params=None) -> list[dict]:
    res = con.execute(sql, params or [])
    # to_arrow_table on DuckDB 1.5+, fetch_arrow_table before (deprecated after)
    return (res.to_arrow_table() if hasattr(res, "to_arrow_table") else res.fetch_arrow_table()).to_pylist()


class Labels:
    def __init__(self, rows):
        self.m = {(l, c): lab for l, c, lab in rows}

    def __call__(self, lst: str | None, code: str | None) -> str | None:
        if not code:
            return None
        return self.m.get((lst, code), code)


def _first(rows, key):
    return next((r[key] for r in rows if r.get(key) is not None), None)


def _in_order(rows: list[dict]) -> list[dict]:
    """Rows of one tender in the order the feed published them."""
    return sorted(rows, key=lambda r: r["pos"])


def _date(ts) -> str | None:
    if ts is None:
        return None
    return ts.date().isoformat() if isinstance(ts, datetime.datetime) else str(ts)[:10]


def to_record(t: dict, rows: dict, L: Labels) -> ProcurementRecord:
    """A tender's staging rows as the record the search index and the graph were built from."""
    results, winners, notices, lots, docs = (_in_order(rows[t]) for t in ("result", "winner", "notice", "lot", "document"))
    by_result = {}
    for w in winners:
        by_result.setdefault(w["result_idx"], w)
    lot_meta = {l["lot_id"]: l for l in lots}
    cpv = list(dict.fromkeys((t["cpv"] or []) + [c for l in lots for c in (l["cpv"] or [])]))
    w0 = winners[0] if winners else {}
    parents = [n for n in (t["auth_parent_names"] or []) if n]
    rec = ProcurementRecord(
        syndication_id=t["entry_id"], category=t["channel"], updated=t["updated"],
        expediente=t["folder_id"], title=t["name"],
        status_code=t["status_code"], status_label=L(LISTS["status"], t["status_code"]),
        status_history=[StatusEvent(h["status_code"], _date(h["first_seen"]))
                        for h in sorted(rows["status_history"], key=lambda h: h["first_seen"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))],
        result_code=_first(results, "result_code"),
        contract_type_code=t["contract_type_code"], contract_type=L(LISTS["contract_type"], t["contract_type_code"]),
        cpv=cpv, procedure_code=t["procedure_code"], procedure=L(LISTS["procedure"], t["procedure_code"]),
        notice_type=notices[0]["type_code"] if notices else None,
        budget_amount=t["budget_tax_excl"] if t["budget_tax_excl"] is not None else t["budget_total"],
        estimated_value=t["value_estimated"],
        awarded_amount=next((r["amount_tax_excl"] if r["amount_tax_excl"] is not None else r["amount_payable"]
                             for r in results if r["amount_tax_excl"] is not None or r["amount_payable"] is not None), None),
        contracting_authority=t["auth_name"],
        contracting_authority_id=(t["auth_ids"] or [":"])[0].split(":", 1)[1] or None,
        org_top_level=parents[-1] if parents else None,
        adjudicatario=w0.get("name"), adjudicatario_nif=w0.get("nif"),
        sme_awarded=_first(results, "sme_awarded"),
        n_bids=int(_first(results, "bids_received")) if _first(results, "bids_received") is not None else None,
        nuts=t["nuts"], nuts_label=L(LISTS["nuts"], t["nuts"]), city=t["auth_city"],
        country=L(LISTS["country"], t["country"] or t["auth_country"]),
        publication_date=next((n["dates"][0] for n in notices if n["dates"]), None),
        award_date=_first(results, "award_date"),
        submission_deadline=t["deadline_date"] or t["participation_deadline_date"],
        funding_program=(t["funding_codes"] or [None])[0],
        document_urls=[d["url"] for d in docs if d["source"] == "general"],
        lots=[Lot(l["lot_id"] or "", l["name"], l["budget_tax_excl"], list(l["cpv"] or [])) for l in lots],
        source_url=t["link"], buyer_profile_url=t["auth_buyer_profile"],
        removed_reason=t["removed_reason"],
    )
    rec.result_label = L(LISTS["result"], rec.result_code)
    for r in results:
        lot_id = (r["lot_ids"] or ["0"])[0]
        w = by_result.get(r["result_idx"], {})
        meta = lot_meta.get(lot_id, {})
        rec.lot_results.append(LotResult(
            lot_id=lot_id, winner_name=w.get("name"), winner_nif=w.get("nif"),
            amount=r["amount_tax_excl"] if r["amount_tax_excl"] is not None else r["amount_payable"],
            award_date=r["award_date"], sme_awarded=r["sme_awarded"],
            n_bids=int(r["bids_received"]) if r["bids_received"] is not None else None,
            n_sme_bids=int(r["sme_bids"]) if r["sme_bids"] is not None else None,
            lower_tender_amount=r["lowest_bid"], higher_tender_amount=r["highest_bid"],
            name=meta.get("name"), cpv=list(meta.get("cpv") or [])))
    return rec


def to_criteria(t: dict, rows: dict, L: Labels) -> dict | None:
    """The platform criteria in the PliegoCriteria shape (parsers' old web-page scrape), or None
    when the feed has no terms and no pliego documents for the tender."""
    crit, reqs, conds = _in_order(rows["criterion"]), _in_order(rows["requirement"]), _in_order(rows["condition"])
    of = lambda kind: [r for r in reqs if r["kind"] == kind]
    guar = {g["type_code"]: g for g in rows["guarantee"] if g["lot_id"] is None} or \
           {g["type_code"]: g for g in rows["guarantee"]}
    order = {"legal": 0, "technical": 1, "additional": 2, "general": 3}
    docs = sorted((d for d in _in_order(rows["document"]) if d["source"] in order), key=lambda d: order[d["source"]])
    links = [{"nombre": f"{_DOC_NAMES[d['source']]}: {d['doc_id'] or d['filename'] or ''}".strip(": ")
              if d["source"] in _DOC_NAMES else (d["filename"] or d["doc_id"] or "Documento"), "url": d["url"]}
             for d in docs]
    if not (crit or reqs or guar or links or conds):
        return None
    dur = None
    if t["duration"] is not None:
        dur = f"{t['duration']:g} {_UNITS.get(t['duration_unit'], t['duration_unit'] or '')}".strip()
    elif t["period_start"] or t["period_end"]:
        dur = f"{t['period_start'] or '?'} – {t['period_end'] or '?'}"
    sub = t["subcontract_text"]
    if t["subcontract_rate"] is not None:
        sub = f"{sub or 'Subcontratación permitida'} (hasta {t['subcontract_rate']:g}%)"
    solv = lambda kind: [{"tipo": L(LISTS[kind], r["type_code"]), "descripcion": r["description"],
                          "umbral": r["threshold"], "lote": r["lot_id"]} for r in of(kind)]
    employees = next((r["threshold"] for r in of("employees") if r["threshold"] is not None), None)
    return {
        "criterios_adjudicacion": [{
            "nombre": c["description"], "ponderacion": c["weight"],
            "subtipo": L(LISTS.get(c["type_code"] or ""), c["subtype_code"]),
            "tipo": {"OBJ": "Evaluable mediante fórmulas", "SUBJ": "Juicio de valor"}.get(c["type_code"] or "", c["type_code"]),
            "nota": c["note"], "lote": c["lot_id"]} for c in crit],
        "garantia_definitiva_pct": (guar.get("2") or {}).get("rate_pct"),
        "garantia_complementaria_pct": (guar.get("3") or {}).get("rate_pct"),
        "garantia_provisional_pct": (guar.get("1") or {}).get("rate_pct"),
        "garantia_plazo_dias": None,
        "clasificacion_empresarial": [r["classification"] or r["description"] for r in of("classification")
                                      if r["classification"] or r["description"]],
        "condiciones_admision": [r["description"] or L(LISTS["declaration"], r["type_code"]) for r in of("declaration")
                                 if r["description"] or r["type_code"]],
        "motivos_exclusion": [r["description"] for r in of("personal_situation") if r["description"]],
        "solvencia_economica": solv("financial"),
        "solvencia_tecnica": solv("technical"),
        "num_empleados_min": int(employees) if employees is not None else None,
        "anos_experiencia_min": next((r["threshold"] for r in of("operating_years") if r["threshold"] is not None), None),
        "plazo_ejecucion": dur,
        "condiciones_especiales": [": ".join(x for x in (c["name"], c["description"]) if x) for c in conds
                                   if c["name"] or c["description"]],
        "subcontratacion": sub,
        "sobres": [], "plazo_validez_oferta": None, "apertura_fecha": None, "apertura_lugar": None,
        "pdf_links": links,
        "descripcion_procedimiento": L(LISTS["procedure"], t["procedure_code"]),
        "directiva_aplicacion": ", ".join(t["eu_legislation"] or []) or None,
        "regulacion_armonizada": bool(t["over_threshold"]),
        "fuente": "feed",
    }


def criteria_uuid(sid: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"criteria_{sid}"))


class Loader:
    def __init__(self, data_dir: str, embedder, upserter, graph_sink=None, chunk: int = CHUNK):
        self.data_dir, self.embedder, self.upserter, self.graph, self.chunk = data_dir, embedder, upserter, graph_sink, chunk
        self.con = duckdb.connect(os.path.join(data_dir, "loaded.duckdb"))
        self.con.execute("CREATE TABLE IF NOT EXISTS loaded (entry_id VARCHAR PRIMARY KEY, fp VARCHAR, loaded_at TIMESTAMPTZ)")

    def _cur(self, t: str) -> str:
        return f"read_parquet('{os.path.join(self.data_dir, 'current', t + '.parquet')}')"

    def _rows(self, sql: str, params) -> list[dict]:
        return fetch_dicts(self.con, sql, params)

    def load(self, limit: int | None = None) -> dict:
        t0 = time.time()
        con = self.con
        L = Labels(con.execute(f"SELECT list, code, label FROM {self._cur('codelist')}").fetchall())
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE todo AS
            SELECT entry_id, fp, (row_number() OVER (ORDER BY entry_id) - 1) // {int(self.chunk)} AS chunk FROM (
                SELECT t.entry_id, t.fp FROM (
                    SELECT entry_id, md5(concat_ws('|', CAST(last_updated AS VARCHAR), coalesce(removed_reason, ''),
                                                   '{LOAD_VERSION}')) AS fp
                    FROM {self._cur('tender')}) t
                LEFT JOIN loaded l USING (entry_id) WHERE l.fp IS DISTINCT FROM t.fp
                ORDER BY t.entry_id {f'LIMIT {int(limit)}' if limit else ''})""")
        n_chunks = con.execute("SELECT coalesce(max(chunk) + 1, 0) FROM todo").fetchone()[0]
        stats = {"tenders": 0, "criteria": 0, "failed_chunks": 0}
        log.info("load_start", chunks=n_chunks)
        for k in range(n_chunks):
            lo, hi = con.execute("SELECT min(entry_id), max(entry_id) FROM todo WHERE chunk = ?", [k]).fetchone()
            keep = "entry_id BETWEEN ? AND ? AND entry_id IN (SELECT entry_id FROM todo WHERE chunk = ?)"
            tenders = self._rows(f"SELECT * FROM {self._cur('tender')} WHERE {keep}", [lo, hi, k])
            rows = {t["entry_id"]: {c: [] for c in CHILDREN} for t in tenders}
            for c in CHILDREN:
                for r in self._rows(f"SELECT * FROM {self._cur(c)} WHERE {keep}", [lo, hi, k]):
                    rows[r["entry_id"]][c].append(r)
            try:
                n_crit = self._write(tenders, rows, L)
            except Exception as exc:  # noqa: BLE001  a failed chunk is retried on the next run
                stats["failed_chunks"] += 1
                log.error("load_chunk_failed", chunk=k, error=str(exc))
                continue
            con.execute("INSERT OR REPLACE INTO loaded SELECT entry_id, fp, now() FROM todo WHERE chunk = ?", [k])
            stats["tenders"] += len(tenders)
            stats["criteria"] += n_crit
            if k % 10 == 0 or k == n_chunks - 1:
                log.info("load_progress", chunk=k + 1, of=n_chunks, tenders=stats["tenders"],
                         seconds=round(time.time() - t0))
        stats["seconds"] = round(time.time() - t0, 1)
        log.info("loaded", **stats)
        return stats

    def _write(self, tenders: list[dict], rows: dict, L: Labels) -> int:
        recs = [to_record(t, rows[t["entry_id"]], L) for t in tenders]
        rendered = [render(r) for r in recs]
        vectors = self.embedder.embed([text for text, _ in rendered])
        self.upserter.upsert_rendered([r.syndication_id for r in recs], [p for _, p in rendered], vectors)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        crit = []
        for t, rec in zip(tenders, recs):
            c = to_criteria(t, rows[t["entry_id"]], L)
            if c is not None:
                crit.append({"class": CRITERIA_CLASS, "id": criteria_uuid(rec.syndication_id), "properties": {
                    "syndication_id": rec.syndication_id, "expediente": rec.expediente or "",
                    "criteria_json": json.dumps(c, ensure_ascii=False), "source_url": rec.source_url or "",
                    "extracted_at": now}})
        if crit:
            self.upserter.post_batch_raw(crit)
        if self.graph is not None:
            self.graph.upsert(recs)
        return len(crit)
