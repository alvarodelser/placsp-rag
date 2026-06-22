from typing import Optional
from .models import RawEntry, ProcurementRecord, StatusEvent
from .codelists import Codelists

NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "pe":  "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "peb": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def first_el(cfs, xpaths: list[str]):
    if cfs is None:
        return None
    for xp in xpaths:
        r = cfs.xpath(xp, namespaces=NS)
        if r:
            return r[0]
    return None


def first_text(cfs, xpaths: list[str]) -> Optional[str]:
    el = first_el(cfs, [xp if xp.endswith("/text()") or "@" in xp else xp + "/text()" for xp in xpaths])
    if el is None:
        return None
    s = str(el).strip()
    return s or None


def all_text(cfs, xpath: str) -> list[str]:
    if cfs is None:
        return []
    return [str(x).strip() for x in cfs.xpath(xpath + "/text()", namespaces=NS) if str(x).strip()]


def _list_uri(cfs, xpath: str) -> Optional[str]:
    el = first_el(cfs, [xpath])
    if el is None:
        return None
    return el.get("listURI") or el.get("listURIID")


def _decode(cl, list_uri, code):
    if cl is None or code is None:
        return code
    return cl.label(list_uri, code) or code


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract(raw: RawEntry, codelists: Optional[Codelists] = None) -> ProcurementRecord:
    cfs = raw.cfs
    rec = ProcurementRecord(syndication_id=raw.syndication_id, category=raw.category, updated=raw.updated)
    rec.source_url = raw.link

    # identity
    rec.expediente = first_text(cfs, ["cbc:ContractFolderID"])
    rec.title = first_text(cfs, ["cac:ProcurementProject/cbc:Name"])

    # status
    rec.status_code = first_text(cfs, ["peb:ContractFolderStatusCode"])
    rec.status_label = _decode(codelists, _list_uri(cfs, "peb:ContractFolderStatusCode"), rec.status_code)
    if rec.status_code:
        rec.status_history = [StatusEvent(code=rec.status_code, date=(raw.updated or "")[:10] or None)]

    # classification
    rec.contract_type_code = first_text(cfs, ["cac:ProcurementProject/cbc:TypeCode"])
    rec.contract_type = _decode(codelists, _list_uri(cfs, "cac:ProcurementProject/cbc:TypeCode"), rec.contract_type_code)
    rec.cpv = all_text(cfs, ".//cac:RequiredCommodityClassification/cbc:ItemClassificationCode")
    rec.procedure_code = first_text(cfs, ["cac:TenderingProcess/cbc:ProcedureCode"])
    rec.procedure = _decode(codelists, _list_uri(cfs, "cac:TenderingProcess/cbc:ProcedureCode"), rec.procedure_code)
    rec.notice_type = first_text(cfs, ["pe:ValidNoticeInfo/peb:NoticeTypeCode"])

    # parties
    rec.contracting_authority = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name"])
    rec.contracting_authority_id = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PartyIdentification/cbc:ID"])
    parents = all_text(cfs, ".//pe:ParentLocatedParty/cac:PartyName/cbc:Name")
    rec.org_top_level = parents[-1] if parents else None
    rec.buyer_profile_url = first_text(cfs, ["pe:LocatedContractingParty/cbc:BuyerProfileURIID"])

    # location
    rec.nuts = first_text(cfs, ["cac:ProcurementProject/cac:RealizedLocation/cbc:CountrySubentityCode"])
    rec.nuts_label = _decode(codelists, _list_uri(cfs, "cac:ProcurementProject/cac:RealizedLocation/cbc:CountrySubentityCode"), rec.nuts)
    rec.city = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PostalAddress/cbc:CityName"])
    rec.country = first_text(cfs, ["cac:ProcurementProject/cac:RealizedLocation/cac:Address/cac:Country/cbc:Name",
                                   "pe:LocatedContractingParty/cac:Party/cac:PostalAddress/cac:Country/cbc:Name"])

    # dates
    rec.publication_date = first_text(cfs, ["pe:ValidNoticeInfo/pe:AdditionalPublicationStatus/pe:AdditionalPublicationDocumentReference/cbc:IssueDate"])
    rec.submission_deadline = first_text(cfs, [".//cac:TenderSubmissionDeadlinePeriod/cbc:EndDate"])
    rec.funding_program = first_text(cfs, ["cac:TenderingTerms/cbc:FundingProgramCode"])

    # documents
    rec.document_urls = all_text(cfs, "pe:GeneralDocument//cac:ExternalReference/cbc:URI")

    # money — three distinct concepts, source-specific paths (first-present wins)
    rec.budget_amount = _num(first_text(cfs, [
        "cac:ProcurementProject/cac:BudgetAmount/cbc:TaxExclusiveAmount",
        "cac:ProcurementProject/cac:BudgetAmount/cbc:TotalAmount"]))
    rec.estimated_value = _num(first_text(cfs, [
        "cac:ProcurementProject/cac:BudgetAmount/cbc:EstimatedOverallContractAmount"]))
    rec.awarded_amount = _num(first_text(cfs, [
        "cac:TenderResult/cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
        "cac:TenderResult/cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"]))

    # tender result
    rec.result_code = first_text(cfs, ["cac:TenderResult/cbc:ResultCode"])
    rec.result_label = _decode(codelists, _list_uri(cfs, "cac:TenderResult/cbc:ResultCode"), rec.result_code)
    rec.award_date = first_text(cfs, ["cac:TenderResult/cbc:AwardDate"])
    rec.adjudicatario = first_text(cfs, ["cac:TenderResult/cac:WinningParty/cac:PartyName/cbc:Name"])
    rec.adjudicatario_nif = first_text(cfs, [".//cac:TenderResult/cac:WinningParty/cac:PartyIdentification/cbc:ID"])
    n = first_text(cfs, ["cac:TenderResult/cbc:ReceivedTenderQuantity"])
    rec.n_bids = int(n) if (n and n.isdigit()) else None
    sme = first_text(cfs, ["cac:TenderResult/cbc:SMEAwardedIndicator"])
    rec.sme_awarded = {"true": True, "false": False}.get((sme or "").lower()) if sme else None

    # lots
    from .models import Lot
    for lot_el in (cfs.xpath("cac:ProcurementProjectLot", namespaces=NS) if cfs is not None else []):
        lid = lot_el.xpath("cbc:ID/text()", namespaces=NS)
        name = lot_el.xpath("cac:ProcurementProject/cbc:Name/text()", namespaces=NS)
        amt = lot_el.xpath(".//cbc:TaxExclusiveAmount/text()", namespaces=NS)
        cpv = [str(x).strip() for x in lot_el.xpath(".//cbc:ItemClassificationCode/text()", namespaces=NS)]
        rec.lots.append(Lot(lot_id=(str(lid[0]) if lid else ""),
                            name=(str(name[0]).strip() if name else None),
                            amount=_num(str(amt[0]) if amt else None),
                            cpv=cpv))

    return rec
