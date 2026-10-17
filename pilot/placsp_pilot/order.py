"""Order an expediente's documents along the procurement lifecycle.

Each document gets an effective date: its own publication date when the platform gives one,
else the date of the notice it belongs to (a PCAP is published with the DOC_CN/DOC_CD notice,
an acta de adjudicación with DOC_CAN_ADJ...). Documents are sorted by that date, then by
lifecycle stage, then by name, and numbered 1..n as `seq`.
"""
from placsp_pilot import classify as C

STAGE = {
    C.PREPARATORY: 0, C.PRIOR_NOTICE: 1, C.TENDER_NOTICE: 2,
    C.PCAP: 3, C.PCAP_PPT: 3, C.PPT: 3, C.ANNEX: 3, C.PROJECT: 3, C.TECHNICAL_ANNEX: 3, C.OTHER: 3,
    C.CLARIFICATION: 4,
    C.BOARD_MINUTES: 5, C.VALUATION_REPORT: 5, C.ABNORMAL_BID_REPORT: 5,
    C.AWARD_PROPOSAL: 6,
    C.AWARD_RESOLUTION: 7, C.AWARD_NOTICE: 7, C.CANCELLATION: 7, C.APPEAL: 7,
    C.CONTRACT_DOCUMENT: 8, C.FORMALIZATION_NOTICE: 8,
    C.MODIFICATION: 9, C.MODIFICATION_NOTICE: 9,
}
# Within one date and stage: the pliegos first, then what complements them.
_ROLE_RANK = {r: i for i, r in enumerate([
    C.PREPARATORY, C.PRIOR_NOTICE, C.TENDER_NOTICE, C.PCAP_PPT, C.PCAP, C.PPT, C.PROJECT, C.TECHNICAL_ANNEX, C.ANNEX,
    C.OTHER, C.CLARIFICATION, C.CANCELLATION, C.BOARD_MINUTES, C.VALUATION_REPORT, C.ABNORMAL_BID_REPORT,
    C.AWARD_PROPOSAL, C.AWARD_RESOLUTION, C.AWARD_NOTICE, C.APPEAL, C.CONTRACT_DOCUMENT, C.FORMALIZATION_NOTICE,
    C.MODIFICATION, C.MODIFICATION_NOTICE])}
STAGE_NAME = ["preparación", "anuncio previo", "anuncio de licitación", "pliegos", "aclaraciones",
              "evaluación", "propuesta", "adjudicación", "formalización", "ejecución"]
# Notices whose date dates the documents of each stage.
_STAGE_NOTICES = {
    1: ("DOC_PIN", "DOC_PIN_RTL", "DOC_CON"), 2: ("DOC_CN", "DOC_CD"), 3: ("DOC_CD", "DOC_CN"),
    4: ("DOC_CN", "DOC_CD"), 5: ("DOC_CAN_ADJ",), 6: ("DOC_CAN_ADJ",), 7: ("DOC_CAN_ADJ", "DOC_CAN_DEF", "DOC_CAN_PROV"),
    8: ("DOC_FORM", "DOC_FORM_ENC"), 9: ("DOC_MOD", "PRO_FORM_ENC"),
}


def notice_dates(tender: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in tender.get("notices", []):
        code, date = (n.get("type") or {}).get("code"), n.get("published")
        if code and date and (code not in out or date < out[code]):
            out[code] = date
    return out


def order_documents(docs: list[dict], tender: dict) -> list[dict]:
    """docs: dicts with sha, role, label, published, notice_type. Returns them sorted, each with
    seq, stage, stage_name, effective_date and date_source added."""
    nd = notice_dates(tender)
    stage_date = {s: min((nd[c] for c in codes if c in nd), default=None) for s, codes in _STAGE_NOTICES.items()}
    stage_date[0] = None
    # An undated stage borrows the nearest earlier dated stage, else the nearest later one.
    filled = {}
    for s in range(10):
        earlier = [stage_date[x] for x in range(s, -1, -1) if stage_date.get(x)]
        later = [stage_date[x] for x in range(s, 10) if stage_date.get(x)]
        filled[s] = (earlier or later or [None])[0]
    out = []
    for d in docs:
        stage = STAGE.get(d.get("role"), 3)
        if d.get("published"):
            date, source = d["published"][:10], "published"
        elif d.get("notice_type") and d["notice_type"] in nd:
            date, source = nd[d["notice_type"]], "notice"
        elif filled.get(stage):
            date, source = filled[stage], "stage"
        else:
            date, source = None, "none"
        out.append(dict(d, stage=stage, stage_name=STAGE_NAME[stage], effective_date=date, date_source=source))
    out.sort(key=lambda d: (d["effective_date"] or "0000", d["stage"], _ROLE_RANK.get(d.get("role"), 99),
                            (d.get("label") or "").lower(), d["sha"]))
    for i, d in enumerate(out, 1):
        d["seq"] = i
    return out
