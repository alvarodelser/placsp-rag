"""Level 1 into the pilot: tenders from the staging tables, the app's record of everything PLACSP
published (src/placsp/staging: every archive since 2012, one row per tender in its latest state).

The pilot used to read the live feeds itself and only saw the latest entries. With the staging
tables it can process any tender, of any year, and its feed facts are the ones the platform keeps:
`record` turns a tender's rows (tender, lot, criterion, requirement, guarantee, condition, result,
winner, modification, notice, document) into the record the pilot's own parser (codice.py) gives,
labels from the codelists, so every later stage reads it unchanged. The documents the feed lists
become the expediente's references; the detail pages, the files and everything after them are
the pilot's levels 2 and 3.

`pick` chooses tenders by channel, year, theme (CPV) and whether they were awarded, newest first.
"""
import json
from pathlib import Path

from placsp_pilot.codelists import Codelists

CHILDREN = ("lot", "criterion", "requirement", "guarantee", "condition", "result", "winner", "modification",
            "notice", "document")
# Stage 1 keeps codes without their listURI: which codelist each one is from.
LISTS = {
    "status": "SyndicationContractFolderStatusCode", "contract_type": "ContractCode",
    "procedure": "SyndicationTenderingProcessCode", "urgency": "DiligenceTypeCode",
    "contracting_system": "ContractingSystemTypeCode", "submission_method": "TenderDeliveryCode",
    "auth_type": "ContractingAuthorityCode", "auth_activity": "ContractingAuthorityActivityCode",
    "guarantee": "GuaranteeTypeCode", "condition": "ExecutionRequirementCode", "funding": "FundingProgramCode",
    "legislation": "ProcurementNationalLegislationCode", "result": "TenderResultCode",
    "notice": "TenderingNoticeTypeCode", "document": "GeneralContractDocuments",
    "financial": "FinancialCapabilityTypeCode", "technical": "TechnicalCapabilityTypeCode",
    "declaration": "DeclarationTypeCode",
    "OBJ": "AwardingCriteriaAutomaticallyEvaluatedSubTypeCode", "SUBJ": "AwardingCriteriaNotAutomaticallyEvaluatedSubTypeCode",
}
SUBTYPE_LIST = {"1": "GoodsContractCode", "2": "ServiceContractCode"}       # by contract type
DOC_SOURCE = {"legal": "feed_legal", "technical": "feed_technical", "additional": "feed_additional",
              "general": "feed_general", "notice": "feed_notice"}


class Labels:
    def __init__(self, codelist_dir: Path):
        self.cl = Codelists(codelist_dir)

    def code(self, list_name: str | None, code) -> dict | None:
        if code in (None, ""):
            return None
        return {"code": code, "label": self.cl.by_name(list_name, code) if list_name else None}


def _place(r: dict, prefix: str = "") -> dict | None:
    loc = {k: r.get(prefix + k) for k in ("nuts", "region", "city", "postal_code") if (prefix + k) in r}
    return loc if any(loc.values()) else None


def _terms(rows: dict, lot: str | None, L: Labels) -> dict:
    out = {"award_criteria": [], "requirements": [], "guarantees": [], "execution_conditions": []}
    for c in (x for x in rows["criterion"] if x["lot_id"] == lot):
        out["award_criteria"].append({
            "lot": lot, "name": c["description"],
            "kind": {"SUBJ": "judgement", "OBJ": "formula"}.get(c["type_code"] or "", c["type_code"]),
            "subtype": L.code(LISTS.get(c["type_code"] or ""), c["subtype_code"]),
            "points": c["weight"], "detail": c["note"], "source": "feed"})
    for q in (x for x in rows["requirement"] if x["lot_id"] == lot):
        kind = q["kind"]
        if kind == "classification":
            typ = {"code": q["type_code"], "label": "Clasificación empresarial"}
            text = q["classification"] or q["description"]
        else:
            typ = L.code(LISTS.get(kind), q["type_code"]) if kind != "personal_situation" else None
            text = q["description"]
        out["requirements"].append({"lot": lot, "group": kind, "type": typ, "text": text,
                                    "threshold": q["threshold"], "source": "feed"})
    out["guarantees"] += [{"lot": lot, "type": L.code(LISTS["guarantee"], g["type_code"]), "amount": g["amount"],
                           "rate_pct": g["rate_pct"]} for g in rows["guarantee"] if g["lot_id"] == lot]
    out["execution_conditions"] += [{"lot": lot, "name": c["name"], "type": L.code(LISTS["condition"], c["type_code"]),
                                     "text": c["description"]} for c in rows["condition"] if c["lot_id"] == lot]
    return out


class _Row(dict):
    """A staging row; a column it lacks (an entry published without its CODICE) reads as empty."""
    def __missing__(self, key):
        return None


def record(t: dict, rows: dict, L: Labels) -> dict:
    """The pilot's record of one tender from its staging rows ({table: [row]}, rows of this tender)."""
    t = _Row(t)
    rows = {k: [_Row(r) for r in rows.get(k, [])] for k in CHILDREN}
    rec = {"id": t["entry_id"], "channel": t["channel"], "updated": t["updated"], "link": t["link"],
           "atom_title": t["atom_title"], "atom_summary": t["atom_summary"], "folder_id": t["folder_id"],
           "status": L.code(LISTS["status"], t["status_code"]), "ted_uuid": t["uuid"], "source": "staging"}
    # Columns of stage 1 as it grows: every id scheme ("NIF:…", "ID_OC_PLAT:…") and list-valued
    # activity and funding codes; tables built before keep the single-valued ones.
    ids = dict(x.split(":", 1) for x in t["auth_ids"] or [] if ":" in x) or \
        {k: v for k, v in (("NIF", t["auth_nif"]), ("DIR3", t["auth_dir3"]), ("ID_PLATAFORMA", t["auth_platform_id"])) if v}
    activity = (list(t["auth_activity_codes"] or []) or [t["auth_activity_code"]])[0]
    funding = (list(t["funding_codes"] or []) or [t["funding_code"]])[0]
    rec["authority"] = {
        "name": t["auth_name"], "ids": ids, "nif": t["auth_nif"], "dir3": t["auth_dir3"], "platform_id": t["auth_platform_id"],
        "type": L.code(LISTS["auth_type"], t["auth_type_code"]), "activity": L.code(LISTS["auth_activity"], activity),
        "website": t["auth_website"], "buyer_profile": t["auth_buyer_profile"], "city": t["auth_city"],
        "postal_code": t["auth_postal_code"], "hierarchy": [n for n in t["auth_parent_names"] or [] if n]}
    duration = {"value": t["duration"], "unit": t["duration_unit"], "start": t["period_start"], "end": t["period_end"]}
    rec["tender"] = {
        "name": t["name"], "contract_type": L.code(LISTS["contract_type"], t["contract_type_code"]),
        "subtype": L.code(SUBTYPE_LIST.get(t["contract_type_code"] or ""), t["subtype_code"]), "mixed": t["mixed"],
        "value_estimated": t["value_estimated"], "budget_tax_excl": t["budget_tax_excl"], "budget_total": t["budget_total"],
        "cpv": list(t["cpv"] or []), "location": _place(t), "duration": duration if any(duration.values()) else None,
        "extension": t["extension_validity"] or t["extension_options"] or t["extension"],
        "procedure": L.code(LISTS["procedure"], t["procedure_code"]),
        "urgency": L.code(LISTS["urgency"], t["urgency_code"]),
        "contracting_system": L.code(LISTS["contracting_system"], t["contracting_system_code"]),
        "submission_method": L.code(LISTS["submission_method"], t["submission_method_code"]),
        "sara": t["over_threshold"], "deadline": {"date": t["deadline_date"], "time": t["deadline_time"]},
        "doc_availability_end": t["doc_availability_end"], "auction": t["auction"]}

    terms = _terms(rows, None, L)
    lots = []
    for lot in rows["lot"]:
        lots.append({"number": lot["lot_id"], "name": lot["name"], "cpv": list(lot["cpv"] or []),
                     "value_estimated": lot["value_estimated"], "budget_tax_excl": lot["budget_tax_excl"],
                     "budget_total": lot["budget_total"], "location": _place(lot)})
        lt = _terms(rows, lot["lot_id"], L)
        for k in terms:
            terms[k].extend(lt[k])
    if not lots:      # the data model always has at least lot 1
        tn = rec["tender"]
        lots.append({"number": "1", "name": None, "cpv": tn["cpv"], "value_estimated": tn["value_estimated"],
                     "budget_tax_excl": tn["budget_tax_excl"], "budget_total": tn["budget_total"],
                     "location": tn["location"], "implicit": True})
    rec["lots"] = lots
    rec.update(terms)
    rec["subcontracting"] = ({"text": t["subcontract_text"], "rate_pct": t["subcontract_rate"]}
                             if t["subcontract_text"] or t["subcontract_rate"] is not None else None)
    rec["terms_other"] = {k: v for k, v in {
        "variants_allowed": t["variants_allowed"], "curricula_required": t["curricula_required"],
        "price_revision": t["price_revision"], "funding": L.code(LISTS["funding"], funding),
        "national_legislation": L.code(LISTS["legislation"], t["national_legislation_code"]),
        "eu_legislation": list(t["eu_legislation"] or []) or None, "appeals_received": t["appeals_received"],
        "language": t["language"]}.items() if v is not None}

    winners = {}
    for w in sorted(rows["winner"], key=lambda w: (w["result_idx"], w["winner_idx"])):
        winners.setdefault(w["result_idx"], []).append({"name": w["name"], "nif": w["nif"], "nuts": w["nuts"], "city": w["city"]})
    rec["results"] = [{
        "lots": list(r["lot_ids"] or []), "result": L.code(LISTS["result"], r["result_code"]), "description": r["description"],
        "award_date": r["award_date"], "start_date": r["start_date"], "bids_received": r["bids_received"],
        "sme_bids": r["sme_bids"], "eu_bids": r["eu_bids"], "non_eu_bids": r["non_eu_bids"],
        "lowest_bid": r["lowest_bid"], "highest_bid": r["highest_bid"],
        "abnormally_low_excluded": r["abnormally_low_excluded"], "sme_awarded": r["sme_awarded"],
        "winners": winners.get(r["result_idx"], []), "amount_tax_excl": r["amount_tax_excl"],
        "amount_payable": r["amount_payable"],
        "contracts": [{"id": i or None, "signed": d or None} for i, d in zip(r["contract_ids"] or [], r["contract_dates"] or [])],
    } for r in sorted(rows["result"], key=lambda r: r["result_idx"])]
    rec["modifications"] = [{"id": m["mod_id"], "note": m["note"], "contract_id": m["contract_id"],
                             "duration_change": m["duration_change"], "final_duration": m["final_duration"],
                             "amount_change": m["amount_change"], "final_amount": m["final_amount"]}
                            for m in rows["modification"]]

    def doc(d: dict, notice_type=None) -> dict:
        typ = L.code(LISTS["document"], d["type_code"])
        out = {"source": DOC_SOURCE.get(d["source"], d["source"]), "label": d["filename"] or d["doc_id"], "url": d["url"],
               "feed_hash": d["hash"], "type_code": d["type_code"], "type_label": typ["label"] if typ else None}
        if notice_type is not None:
            out["notice_type"] = notice_type
        return out

    notices, docs = [], []
    for n in sorted(rows["notice"], key=lambda n: n["notice_idx"]):
        ntype = L.code(LISTS["notice"], n["type_code"])
        nd = [doc(d, n["type_code"]) for d in rows["document"] if d["source"] == "notice" and d["notice_idx"] == n["notice_idx"]]
        dates = list(n["dates"] or [])
        notices.append({"type": ntype, "media": list(n["media"] or []), "dates": dates, "docs": nd,
                        "published": min(dates) if dates else None})
        docs += nd
    for src in ("legal", "technical", "additional", "general"):
        docs += [doc(d) for d in rows["document"] if d["source"] == src]
    rec["notices"] = notices
    rec["documents"] = docs
    return rec


class Staging:
    """The stage-1 `current/` tables of a data dir, read with DuckDB."""

    def __init__(self, data_dir: str | Path, codelist_dir: Path):
        import duckdb
        self.dir = Path(data_dir) / "current"
        if not (self.dir / "tender.parquet").exists():
            raise SystemExit(f"no staging tables in {self.dir} (run `placsp stage all` first)")
        self.con = duckdb.connect()
        self.labels = Labels(codelist_dir)

    def _t(self, table: str) -> str:
        return f"read_parquet('{self.dir / (table + '.parquet')}')"

    def _rows(self, sql: str, params=()) -> list[dict]:
        cur = self.con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def pick(self, n: int, channels: list[str] | None = None, years: list[int] | None = None,
             theme: str | None = None, awarded: bool | None = None, exclude: set[str] = frozenset(),
             with_documents: bool = True) -> list[str]:
        """Entry ids, newest first. A theme is matched as the pilot matches it (themes.cpv_themes:
        exact roots, exclusions); SQL only narrows to the CPV divisions it can be in."""
        from placsp_pilot.themes import THEMES, cpv_themes
        cpv_prefixes = [c.lstrip("=")[:2] for c in THEMES[theme]["cpv"]] if theme else None
        where, params = ["coalesce(CAST(removed_reason AS VARCHAR), '') <> 'ANULADA'"], []    # annulled publications out
        if channels:
            where.append(f"channel IN ({','.join('?' * len(channels))})")
            params += channels
        if years:
            where.append(f"year(try_cast(updated AS TIMESTAMPTZ)) IN ({','.join('?' * len(years))})")
            params += years
        if cpv_prefixes:
            where.append("list_has_any(list_transform(cpv, c -> substr(c, 1, 2)), ?)")
            params.append(sorted(set(cpv_prefixes)))
        if awarded is not None:
            where.append(("" if awarded else "NOT ") + f"entry_id IN (SELECT entry_id FROM {self._t('winner')})")
        if with_documents:
            where.append(f"entry_id IN (SELECT entry_id FROM {self._t('document')} WHERE source IN ('legal', 'technical'))")
        rows = self.con.execute(f"SELECT entry_id, cpv FROM {self._t('tender')} WHERE {' AND '.join(where)}"
                                f" ORDER BY last_updated DESC" + ("" if theme else f" LIMIT {int(n + len(exclude))}"), params).fetchall()
        out = []
        for eid, cpv in rows:
            if eid in exclude:
                continue
            if theme and not any(theme in cpv_themes(c) for c in cpv or []):
                continue
            out.append(eid)
            if len(out) >= n:
                break
        return out

    def record(self, entry_id: str) -> dict | None:
        ts = self._rows(f"SELECT * FROM {self._t('tender')} WHERE entry_id = ?", (entry_id,))
        if not ts:
            return None
        rows = {t: self._rows(f"SELECT * FROM {self._t(t)} WHERE entry_id = ?", (entry_id,)) for t in CHILDREN}
        return record(ts[0], rows, self.labels)


_COMPANIES: dict[str, dict[str, str]] = {}


def company_index(data_dir: str | Path) -> dict[str, str]:
    """Every name a winner has been published under, normalised (graph.norm_name) -> its NIF, from
    stage 1's `company` table: a bidder an acta names without its NIF gets it when the name is one a
    winner used. A name used by two NIFs is left out."""
    key = str(data_dir)
    if key not in _COMPANIES:
        import duckdb
        from placsp_pilot.graph import norm_name
        path = Path(data_dir) / "current" / "company.parquet"
        seen: dict[str, str | None] = {}
        if path.exists():
            for nif, names in duckdb.connect().execute(f"SELECT nif_norm, names FROM read_parquet('{path}')").fetchall():
                for n in names or []:
                    k = norm_name(n)
                    if len(k) >= 4 and nif:
                        seen[k] = nif if seen.get(k, nif) == nif else None
        _COMPANIES[key] = {k: v for k, v in seen.items() if v}
    return _COMPANIES[key]


def to_json(rec: dict) -> bytes:
    return json.dumps(rec, ensure_ascii=False, default=str).encode()
