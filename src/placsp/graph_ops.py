from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional
from .models import ProcurementRecord

_LEGAL_SUFFIXES = {
    "SL", "SLU", "SLL", "SA", "SAU", "SCA", "SC", "SLP", "SLNE",
    "SCOOP", "COOP", "SRL", "SAL", "AIE", "UTE",
}

def normalize_nif(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    out = re.sub(r"[\s.\-]", "", s).upper()
    return out or None

def normalize_name(s: Optional[str]) -> str:
    if not s:
        return ""
    # First collapse all non-alphanumeric to spaces, then split
    # This will turn "S.L.L." into "S L L" after split
    normalized = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", " ", s).upper().split()
    # Try to collapse letters back together: consecutive single-letter tokens
    # e.g., ["S", "L", "L"] might become ["SLL"]
    tokens = []
    current = ""
    for tok in normalized:
        if len(tok) == 1:
            current += tok
        else:
            if current:
                tokens.append(current)
                current = ""
            tokens.append(tok)
    if current:
        tokens.append(current)
    # Now filter out legal suffixes
    kept = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(kept or tokens).strip()

def is_ute_winner(name: Optional[str], nif: Optional[str]) -> bool:
    n = normalize_nif(nif)
    if n and n.startswith("U"):
        return True
    return bool(name and name.strip().upper().startswith("UTE"))

@dataclass
class GraphBatch:
    companies: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    won: list[dict] = field(default_factory=list)
    authorities: list[dict] = field(default_factory=list)
    tendered: list[dict] = field(default_factory=list)
    classified: list[dict] = field(default_factory=list)
    located: list[dict] = field(default_factory=list)
    affected_nifs: list[str] = field(default_factory=list)

def record_to_graph_ops(rec: ProcurementRecord) -> GraphBatch:
    b = GraphBatch()
    winners = [lr for lr in rec.lot_results if normalize_nif(lr.winner_nif)]
    if not winners:
        return b  # awarded-only: no graphable winner → emit nothing

    sid = rec.syndication_id
    b.contracts.append({
        "syndication_id": sid,
        "props": {
            "expediente": rec.expediente, "title": rec.title,
            "status_code": rec.status_code, "result_code": rec.result_code,
            "contract_type_code": rec.contract_type_code,
            "procedure_code": rec.procedure_code,
            "budget_amount": rec.budget_amount, "estimated_value": rec.estimated_value,
            "award_date": rec.award_date, "publication_date": rec.publication_date,
            "category": rec.category,
        },
    })
    if rec.contracting_authority_id:
        b.authorities.append({"id": rec.contracting_authority_id,
                              "name": rec.contracting_authority,
                              "org_top_level": rec.org_top_level})
        b.tendered.append({"authority_id": rec.contracting_authority_id, "syndication_id": sid})
    if rec.nuts:
        b.located.append({"syndication_id": sid, "nuts": rec.nuts})

    seen_nifs = set()
    for lr in winners:
        nif = normalize_nif(lr.winner_nif)
        lot_key = f"{sid}:{lr.lot_id}"
        if nif not in seen_nifs:
            b.companies.append({"nif": nif, "is_ute": is_ute_winner(lr.winner_name, lr.winner_nif)})
            b.affected_nifs.append(nif)
            seen_nifs.add(nif)
        b.lots.append({
            "lot_key": lot_key, "syndication_id": sid,
            "n_bids": lr.n_bids, "n_sme_bids": lr.n_sme_bids,
            "lower_tender_amount": lr.lower_tender_amount,
            "higher_tender_amount": lr.higher_tender_amount,
            "props": {
                "name": lr.name, "amount": lr.amount, "award_date": lr.award_date,
                "sme_awarded": lr.sme_awarded,
            },
        })
        b.won.append({"nif": nif, "lot_key": lot_key, "amount": lr.amount,
                      "award_date": lr.award_date,
                      "name_norm": normalize_name(lr.winner_name),
                      "name_display": lr.winner_name})
        for code in lr.cpv:
            if code:
                b.classified.append({"lot_key": lot_key, "cpv": code})
    return b

def merge_batches(batches: list[GraphBatch]) -> GraphBatch:
    out = GraphBatch()
    for b in batches:
        out.companies += b.companies
        out.contracts += b.contracts
        out.lots += b.lots
        out.won += b.won
        out.authorities += b.authorities
        out.tendered += b.tendered
        out.classified += b.classified
        out.located += b.located
        out.affected_nifs += b.affected_nifs
    return out
