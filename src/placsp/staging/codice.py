"""Flatten one ATOM entry (its CODICE ContractFolderStatus) into staging rows, one list per table.

Paths match on local names ({*}), so the CODICE and CODICE-PLACE namespaces need not be spelled
out, and every field is read where PLACSP puts it in any channel. Nothing is decoded here: codes
stay codes (labels come from the codelist table) and dates stay as published.
"""
from lxml import etree

ATOM = "{http://www.w3.org/2005/Atom}"


def _path(names) -> str:
    return "/".join("{*}" + n for n in names)


def kid(el, *names):
    return None if el is None else el.find(_path(names))


def kids(el, *names) -> list:
    return [] if el is None else el.findall(_path(names))


def txt(el, *names) -> str | None:
    e = kid(el, *names) if names else el
    if e is None or e.text is None:
        return None
    return e.text.strip() or None


def num(el, *names) -> float | None:
    t = txt(el, *names)
    try:
        return float(t) if t is not None else None
    except ValueError:
        return None


def integer(el, *names) -> int | None:
    n = num(el, *names)
    return int(n) if n is not None else None


def flag(el, *names) -> bool | None:
    t = txt(el, *names)
    return None if t is None else t.lower() == "true"


def ids(party) -> dict[str, str]:
    return {(i.get("schemeName") or "ID"): i.text.strip()
            for i in kids(party, "PartyIdentification", "ID") if i.text and i.text.strip()}


def entry_id(atom_id: str | None) -> str:
    return (atom_id or "").rstrip("/").rsplit("/", 1)[-1]


def texts(el, *names) -> list[str]:
    return [x.text.strip() for x in kids(el, *names) if x.text and x.text.strip()]


def _place(loc) -> dict:
    return {"nuts": txt(loc, "CountrySubentityCode"), "region": txt(loc, "CountrySubentity"),
            "street": txt(loc, "Address", "StreetName"),
            "city": txt(loc, "Address", "CityName"), "postal_code": txt(loc, "Address", "PostalZone"),
            "country": txt(loc, "Address", "Country", "IdentificationCode")}


def _budget(pp) -> dict:
    b = kid(pp, "BudgetAmount")
    return {"value_estimated": num(b, "EstimatedOverallContractAmount"),
            "budget_tax_excl": num(b, "TaxExclusiveAmount"), "budget_total": num(b, "TotalAmount")}


def _cpv(pp) -> list[str]:
    return [c for c in (txt(r, "ItemClassificationCode") for r in kids(pp, "RequiredCommodityClassification")) if c]


def _terms(tt, lot_id: str | None, vkey: str, out: dict):
    """TenderingTerms (of the folder, lot_id None, or of one lot) -> criterion, requirement,
    guarantee and condition rows."""
    if tt is None:
        return
    for i, ac in enumerate(kids(tt, "AwardingTerms", "AwardingCriteria")):
        out["criterion"].append({
            "vkey": vkey, "lot_id": lot_id, "idx": i, "type_code": txt(ac, "AwardingCriteriaTypeCode"),
            "subtype_code": txt(ac, "AwardingCriteriaSubTypeCode"), "description": txt(ac, "Description"),
            "weight": num(ac, "WeightNumeric"), "note": txt(ac, "Note")})
    reqs = []
    for qr in kids(tt, "TendererQualificationRequest"):
        for tag, kind in (("FinancialEvaluationCriteria", "financial"), ("TechnicalEvaluationCriteria", "technical")):
            reqs += [(kind, txt(c, "EvaluationCriteriaTypeCode"), txt(c, "Description"),
                      num(c, "ThresholdQuantity"), None) for c in kids(qr, tag)]
        reqs += [("declaration", txt(c, "RequirementTypeCode"), txt(c, "Description"), None, None)
                 for c in kids(qr, "SpecificTendererRequirement")]
        for s in kids(qr, "RequiredBusinessClassificationScheme"):
            reqs += [("classification", txt(s, "ID"), txt(cat, "Description"), None, txt(cat, "CodeValue"))
                     for cat in kids(s, "ClassificationCategory")]
        reqs += [("personal_situation", None, txt(c, "Description") or txt(c), None, None)
                 for c in kids(qr, "PersonalSituation")]
        for tag, desc, kind in (("EmployeeQuantity", "EmployeeQuantityDescription", "employees"),
                                ("OperatingYearsQuantity", "OperatingYearsDescription", "operating_years")):
            if kid(qr, tag) is not None or kid(qr, desc) is not None:
                reqs.append((kind, None, " | ".join(texts(qr, desc)) or None, num(qr, tag), None))
        d = txt(qr, "Description")
        if d:
            reqs.append(("general", None, d, None, None))
    out["requirement"] += [{"vkey": vkey, "lot_id": lot_id, "idx": i, "kind": k, "type_code": t,
                            "description": d, "threshold": th, "classification": cl}
                           for i, (k, t, d, th, cl) in enumerate(reqs)]
    out["guarantee"] += [{"vkey": vkey, "lot_id": lot_id, "type_code": txt(g, "GuaranteeTypeCode"),
                          "amount": num(g, "LiabilityAmount"), "rate_pct": num(g, "AmountRate"),
                          "duration": num(g, "ConstitutionPeriod", "DurationMeasure")}
                         for g in kids(tt, "RequiredFinancialGuarantee")]
    out["condition"] += [{"vkey": vkey, "lot_id": lot_id, "type_code": txt(r, "ExecutionRequirementCode"),
                          "name": txt(r, "Name"), "description": txt(r, "Description")}
                         for r in kids(tt, "ContractExecutionRequirement")]


def _doc(el, vkey: str, source: str, notice_idx: int | None = None) -> dict | None:
    ext = kid(el, "Attachment", "ExternalReference")
    url = txt(ext, "URI")
    if not url:
        return None
    return {"vkey": vkey, "source": source, "notice_idx": notice_idx, "doc_id": txt(el, "ID"),
            "type_code": txt(el, "DocumentTypeCode"), "filename": txt(ext, "FileName"),
            "url": url, "hash": txt(ext, "DocumentHash")}


def empty() -> dict[str, list]:
    from placsp.staging.tables import TABLES
    return {t: [] for t in TABLES}


def flatten(entry, vkey: str, channel: str, src_zip: str, src_file: str, out: dict):
    """Append the rows of one <entry> element to out ({table: [row]}). Child rows get `pos`, their
    position within the entry as published, since table order is not kept downstream."""
    start = {t: len(rows) for t, rows in out.items()}
    _flatten(entry, vkey, channel, src_zip, src_file, out)
    for t, rows in out.items():
        if t not in ("entry", "tombstone"):
            for i, r in enumerate(rows[start[t]:]):
                r["pos"] = i


def _flatten(entry, vkey: str, channel: str, src_zip: str, src_file: str, out: dict):
    link = entry.find(f"{ATOM}link")
    row = {"vkey": vkey, "entry_id": entry_id(entry.findtext(f"{ATOM}id")), "channel": channel,
           "src_zip": src_zip, "src_file": src_file, "updated": entry.findtext(f"{ATOM}updated"),
           "link": link.get("href") if link is not None else None,
           "atom_title": entry.findtext(f"{ATOM}title"), "atom_summary": entry.findtext(f"{ATOM}summary")}
    cfs = kid(entry, "ContractFolderStatus")
    out["entry"].append(row)
    if cfs is None:
        return

    lcp = kid(cfs, "LocatedContractingParty")
    party = kid(lcp, "Party")
    pid = ids(party)
    parents, p = [], kid(lcp, "ParentLocatedParty")
    while p is not None:
        name, pids = txt(p, "PartyName", "Name"), ids(p)
        if name or pids:            # feeds often close the chain with an empty element
            parents.append((name or "", next(iter(pids.values()), "")))
        p = kid(p, "ParentLocatedParty")
    pp = kid(cfs, "ProcurementProject")
    tp = kid(cfs, "TenderingProcess")
    tt = kid(cfs, "TenderingTerms")
    ext = kid(pp, "ContractExtension")
    period = kid(pp, "PlannedPeriod")
    place = _place(kid(pp, "RealizedLocation"))
    sub = kid(tt, "AllowedSubcontractTerms")
    row.update({
        "folder_id": txt(cfs, "ContractFolderID"), "status_code": txt(cfs, "ContractFolderStatusCode"),
        "uuid": txt(cfs, "UUID"),
        "auth_name": txt(party, "PartyName", "Name"), "auth_nif": pid.get("NIF"), "auth_dir3": pid.get("DIR3"),
        "auth_platform_id": pid.get("ID_PLATAFORMA"), "auth_ids": [f"{k}:{v}" for k, v in pid.items()], "auth_type_code": txt(lcp, "ContractingPartyTypeCode"),
        "auth_activity_codes": texts(lcp, "ActivityCode"), "auth_website": txt(party, "WebsiteURI"),
        "auth_buyer_profile": txt(lcp, "BuyerProfileURIID"),
        "auth_address": txt(party, "PostalAddress", "AddressLine", "Line"),
        "auth_city": txt(party, "PostalAddress", "CityName"), "auth_postal_code": txt(party, "PostalAddress", "PostalZone"),
        "auth_country": txt(party, "PostalAddress", "Country", "IdentificationCode"),
        "auth_contact_name": txt(party, "Contact", "Name"), "auth_email": txt(party, "Contact", "ElectronicMail"),
        "auth_phone": txt(party, "Contact", "Telephone"),
        "auth_parent_names": [n for n, _ in parents], "auth_parent_ids": [i for _, i in parents],
        "agent_name": txt(party, "AgentParty", "PartyName", "Name"),
        "agent_id": next(iter(ids(kid(party, "AgentParty")).values()), None),
        "name": txt(pp, "Name"), "contract_type_code": txt(pp, "TypeCode"), "subtype_code": txt(pp, "SubTypeCode"),
        "mixed": flag(pp, "MixContractIndicator"), **_budget(pp), "cpv": _cpv(pp), **place,
        "duration": num(period, "DurationMeasure"),
        "duration_unit": kid(period, "DurationMeasure").get("unitCode") if kid(period, "DurationMeasure") is not None else None,
        "period_start": txt(period, "StartDate"), "period_end": txt(period, "EndDate"),
        "extension_validity": txt(ext, "OptionValidityPeriod", "Description"),
        "extension_options": txt(ext, "OptionsDescription"),
        "procedure_code": txt(tp, "ProcedureCode"), "urgency_code": txt(tp, "UrgencyCode"),
        "contracting_system_code": txt(tp, "ContractingSystemCode"),
        "submission_method_code": txt(tp, "SubmissionMethodCode"), "over_threshold": flag(tp, "OverThresholdIndicator"),
        "deadline_date": txt(tp, "TenderSubmissionDeadlinePeriod", "EndDate"),
        "deadline_time": txt(tp, "TenderSubmissionDeadlinePeriod", "EndTime"),
        "participation_deadline_date": txt(tp, "ParticipationRequestReceptionPeriod", "EndDate"),
        "participation_deadline_time": txt(tp, "ParticipationRequestReceptionPeriod", "EndTime"),
        "participation_deadline_note": txt(tp, "ParticipationRequestReceptionPeriod", "Description"),
        "doc_availability_end": txt(tp, "DocumentAvailabilityPeriod", "EndDate"),
        "doc_availability_end_time": txt(tp, "DocumentAvailabilityPeriod", "EndTime"),
        "tender_recipient": txt(tt, "TenderRecipientParty", "EndpointID"),
        "deadline_note": txt(tp, "TenderSubmissionDeadlinePeriod", "Description"),
        "auction": flag(tp, "AuctionTerms", "AuctionConstraintIndicator"),
        "part_presentation_code": txt(tp, "PartPresentationCode"),
        "max_lots_tender": integer(tp, "MaximumLotPresentationQuantity"),
        "max_lots_award": integer(tp, "MaximumTendererAwardedLotsQuantity"),
        "lots_combination": txt(tp, "LotsCombinationContractingAuthorityRights"),
        "shortlist_min": integer(tp, "EconomicOperatorShortList", "MinimumQuantity"),
        "shortlist_max": integer(tp, "EconomicOperatorShortList", "MaximumQuantity"),
        "shortlist_expected": integer(tp, "EconomicOperatorShortList", "ExpectedQuantity"),
        "shortlist_criteria": txt(tp, "EconomicOperatorShortList", "LimitationDescription"),
        "funding_codes": texts(tt, "FundingProgramCode"), "funding_text": txt(tt, "FundingProgram"),
        "national_legislation_code": txt(tt, "ProcurementNationalLegislationCode"),
        "eu_legislation": [x for x in (txt(r, "ID") for r in kids(tt, "ProcurementLegislationDocumentReference")) if x],
        "variants_allowed": flag(tt, "VariantConstraintIndicator"),
        "curricula_required": flag(tt, "RequiredCurriculaIndicator"),
        "price_revision": txt(tt, "PriceRevisionFormulaDescription"),
        "subcontract_text": txt(sub, "Description"), "subcontract_rate": num(sub, "Rate"),
        "appeals_received": num(tt, "ReceivedAppealQuantity"), "language": txt(tt, "Language", "ID"),
    })

    _terms(tt, None, vkey, out)
    for lot in kids(cfs, "ProcurementProjectLot"):
        lid = txt(lot, "ID")
        lpp = kid(lot, "ProcurementProject")
        lp = _place(kid(lpp, "RealizedLocation"))
        out["lot"].append({"vkey": vkey, "lot_id": lid, "name": txt(lpp, "Name"), "cpv": _cpv(lpp), **_budget(lpp),
                           "nuts": lp["nuts"], "region": lp["region"], "city": lp["city"], "street": lp["street"]})
        _terms(kid(lot, "TenderingTerms"), lid, vkey, out)

    for ri, tr in enumerate(kids(cfs, "TenderResult")):
        atp = kid(tr, "AwardedTenderedProject")
        contracts = kids(tr, "Contract")
        out["result"].append({
            "vkey": vkey, "result_idx": ri,
            "lot_ids": [x.text.strip() for x in kids(atp, "ProcurementProjectLotID") if x.text and x.text.strip()],
            "result_code": txt(tr, "ResultCode"), "description": txt(tr, "Description"),
            "award_date": txt(tr, "AwardDate"), "start_date": txt(tr, "StartDate"),
            "bids_received": num(tr, "ReceivedTenderQuantity"), "sme_bids": num(tr, "SMEsReceivedTenderQuantity"),
            "eu_bids": num(tr, "EUNationalsReceivedTenderQuantity"),
            "non_eu_bids": num(tr, "NonEUNationalsReceivedTenderQuantity"),
            "electronic_bids": num(tr, "ReceivedElectronicTenderQuantity"),
            "lowest_bid": num(tr, "LowerTenderAmount"), "highest_bid": num(tr, "HigherTenderAmount"),
            "abnormally_low_excluded": flag(tr, "AbnormallyLowTendersIndicator"),
            "sme_awarded": flag(tr, "SMEAwardedIndicator"),
            "winner_nationality": txt(tr, "AwardedOwnerNationalityCode"),
            "subcontract_rate": num(tr, "SubcontractTerms", "Rate"),
            "subcontract_text": txt(tr, "SubcontractTerms", "Description"),
            "amount_tax_excl": num(atp, "LegalMonetaryTotal", "TaxExclusiveAmount"),
            "amount_payable": num(atp, "LegalMonetaryTotal", "PayableAmount"),
            "contract_ids": [txt(c, "ID") or "" for c in contracts],
            "contract_dates": [txt(c, "IssueDate") or "" for c in contracts]})
        for wi, wp in enumerate(kids(tr, "WinningParty")):
            wid = ids(wp)
            scheme, nif = (("NIF", wid["NIF"]) if "NIF" in wid else next(iter(wid.items()), (None, None)))
            loc = kid(wp, "PhysicalLocation")
            out["winner"].append({
                "vkey": vkey, "result_idx": ri, "winner_idx": wi, "name": txt(wp, "PartyName", "Name"),
                "nif": nif, "id_scheme": scheme, "nuts": txt(loc, "CountrySubentityCode"),
                "city": txt(loc, "Address", "CityName"), "postal_code": txt(loc, "Address", "PostalZone"),
                "country": txt(loc, "Address", "Country", "IdentificationCode")})

    out["modification"] += [{
        "vkey": vkey, "mod_id": txt(m, "ID"), "contract_id": txt(m, "ContractID"), "note": txt(m, "Note"),
        "duration_change": num(m, "ContractModificationDurationMeasure"),
        "final_duration": num(m, "FinalDurationMeasure"),
        "amount_change": num(m, "ContractModificationLegalMonetaryTotal", "TaxExclusiveAmount"),
        "final_amount": num(m, "FinalLegalMonetaryTotal", "TaxExclusiveAmount")} for m in kids(cfs, "ContractModification")]

    for ni, vn in enumerate(kids(cfs, "ValidNoticeInfo")):
        media, dates, sent_to, sent_dates, sent_times = [], [], [], [], []
        for st in kids(vn, "AdditionalPublicationStatus"):
            if txt(st, "PublicationMediaName"):
                media.append(txt(st, "PublicationMediaName"))
            for rq in kids(st, "AdditionalPublicationRequest"):
                sent_to.append(txt(rq, "AgencyID") or "")
                sent_dates.append(txt(rq, "SendDate") or "")
                sent_times.append(txt(rq, "SendTime") or "")
            for ref in kids(st, "AdditionalPublicationDocumentReference"):
                if txt(ref, "IssueDate"):
                    dates.append(txt(ref, "IssueDate"))
                d = _doc(ref, vkey, "notice", ni)
                if d:
                    out["document"].append(d)
        out["notice"].append({"vkey": vkey, "notice_idx": ni, "type_code": txt(vn, "NoticeTypeCode"),
                              "media": media, "dates": dates, "sent_to": sent_to, "sent_dates": sent_dates,
                              "sent_times": sent_times})
    for tag, source in (("LegalDocumentReference", "legal"), ("TechnicalDocumentReference", "technical"),
                        ("AdditionalDocumentReference", "additional")):
        out["document"] += [d for d in (_doc(el, vkey, source) for el in kids(cfs, tag)) if d]
    out["document"] += [d for d in (_doc(el, vkey, "general")
                                    for el in kids(cfs, "GeneralDocument", "GeneralDocumentDocumentReference")) if d]


def tombstone(el, channel: str, src_zip: str, src_file: str) -> dict:
    c = next((x for x in el if isinstance(x.tag, str) and x.tag.endswith("comment")), None)
    return {"entry_id": entry_id(el.get("ref")), "channel": channel, "src_zip": src_zip, "src_file": src_file,
            "when": el.get("when"), "reason": c.get("type") if c is not None else None}


def iter_feed(fh):
    """Yield ("entry", el) and ("tombstone", el) from an ATOM stream, freeing each element after use."""
    for _, el in etree.iterparse(fh, events=("end",), huge_tree=True):
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == f"{ATOM}entry":
            yield "entry", el
        elif tag.endswith("}deleted-entry"):
            yield "tombstone", el
        else:
            continue
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
