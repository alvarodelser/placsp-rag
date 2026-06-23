import re
from dataclasses import asdict
from .models import ProcurementRecord

_DATE_ONLY = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")

def _money(v):
    return f"{v:,.2f} EUR" if v is not None else None

def render(rec: ProcurementRecord) -> tuple[str, dict]:
    parts: list[str] = []
    tipo = rec.contract_type or rec.contract_type_code
    if tipo and rec.title:
        parts.append(f"Contrato de {tipo}: {rec.title}.")
    elif rec.title:
        parts.append(f"{rec.title}.")
    if rec.contracting_authority:
        org = rec.contracting_authority
        if rec.org_top_level and rec.org_top_level != org:
            org += f" ({rec.org_top_level})"
        parts.append(f"Órgano de contratación: {org}.")
    if rec.expediente:
        parts.append(f"Expediente: {rec.expediente}.")
    money = []
    if rec.budget_amount is not None: money.append(f"presupuesto base {_money(rec.budget_amount)}")
    if rec.estimated_value is not None: money.append(f"valor estimado {_money(rec.estimated_value)}")
    if rec.awarded_amount is not None: money.append(f"importe de adjudicación {_money(rec.awarded_amount)}")
    if money:
        parts.append("Importes: " + ", ".join(money) + ".")
    if rec.cpv:
        parts.append("CPV: " + ", ".join(rec.cpv) + ".")
    if rec.procedure:
        parts.append(f"Procedimiento: {rec.procedure}.")
    estado = rec.status_label or rec.status_code
    if estado:
        parts.append(f"Estado: {estado}.")
    if rec.adjudicatario:
        parts.append(f"Adjudicatario: {rec.adjudicatario}.")
    if rec.nuts_label or rec.nuts:
        parts.append(f"Lugar de ejecución: {rec.nuts_label or rec.nuts}.")
    if rec.funding_program:
        parts.append(f"Programa de financiación: {rec.funding_program}.")
    if rec.publication_date:
        parts.append(f"Fecha de publicación: {rec.publication_date}.")
    summary = " ".join(parts)

    _DATE_FIELDS = {"publication_date", "award_date", "submission_deadline", "updated"}

    props = asdict(rec)
    props["content"] = summary
    # serialize nested
    props["status_history"] = [asdict(e) for e in rec.status_history]
    props["lots"] = [asdict(l) for l in rec.lots]
    # RFC3339: Weaviate date fields require a full timestamp. Source values that
    # already carry a time component (contain "T", e.g. updated) are left as-is;
    # date-only values are normalized from their YYYY-MM-DD prefix, tolerating
    # junk like a stray trailing "Z". Anything unparseable is dropped.
    for f in _DATE_FIELDS:
        v = props.get(f)
        if not v or "T" in v:
            continue
        m = _DATE_ONLY.match(v)
        props[f] = m.group(1) + "T00:00:00Z" if m else None
    # drop empty/None scalars (keep required + lists)
    keep_always = {"syndication_id", "category", "content", "status_history", "lots", "cpv", "document_urls"}
    props = {k: v for k, v in props.items()
             if k in keep_always or (v is not None and v != [] and v != "")}
    return summary, props
