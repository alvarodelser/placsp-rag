from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class RawEntry:
    syndication_id: str
    updated: Optional[str]
    link: Optional[str]
    cfs: Any            # lxml ContractFolderStatus element; valid only until next parse iteration
    category: str

@dataclass
class Tombstone:
    syndication_id: str
    when: Optional[str]
    reason: Optional[str]
    category: str

@dataclass
class Lot:
    lot_id: str
    name: Optional[str] = None
    amount: Optional[float] = None
    cpv: list[str] = field(default_factory=list)

@dataclass
class StatusEvent:
    code: str
    date: Optional[str] = None

@dataclass
class ProcurementRecord:
    syndication_id: str
    category: str
    updated: Optional[str]
    expediente: Optional[str] = None
    title: Optional[str] = None
    status_code: Optional[str] = None
    status_label: Optional[str] = None
    status_history: list[StatusEvent] = field(default_factory=list)
    result_code: Optional[str] = None
    result_label: Optional[str] = None
    contract_type_code: Optional[str] = None
    contract_type: Optional[str] = None
    cpv: list[str] = field(default_factory=list)
    procedure_code: Optional[str] = None
    procedure: Optional[str] = None
    notice_type: Optional[str] = None
    budget_amount: Optional[float] = None
    estimated_value: Optional[float] = None
    awarded_amount: Optional[float] = None
    contracting_authority: Optional[str] = None
    contracting_authority_id: Optional[str] = None
    org_top_level: Optional[str] = None
    adjudicatario: Optional[str] = None
    adjudicatario_nif: Optional[str] = None
    sme_awarded: Optional[bool] = None
    n_bids: Optional[int] = None
    nuts: Optional[str] = None
    nuts_label: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    publication_date: Optional[str] = None
    award_date: Optional[str] = None
    submission_deadline: Optional[str] = None
    funding_program: Optional[str] = None
    document_urls: list[str] = field(default_factory=list)
    lots: list[Lot] = field(default_factory=list)
    source_url: Optional[str] = None
    buyer_profile_url: Optional[str] = None
    lang: str = "es"
