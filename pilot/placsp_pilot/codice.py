"""Full CODICE ContractFolderStatus parse for the pilot.

Unlike the production extractor, this keeps everything the data model needs:
every notice and its documents, the typed PCAP/PPT/annex references, general
documents with their type code, lot-level terms, award criteria, solvency
requirements, guarantees, results per lot and contract modifications.
"""
from lxml import etree

from placsp_pilot.codelists import Codelists

ATOM = "{http://www.w3.org/2005/Atom}"


def _path(*names: str) -> str:
    return "/".join("{*}" + n for n in names)


def kid(el, *names):
    if el is None:
        return None
    return el.find(_path(*names))


def kids(el, *names) -> list:
    if el is None:
        return []
    return el.findall(_path(*names))


def txt(el, *names) -> str | None:
    e = kid(el, *names) if names else el
    if e is None or e.text is None:
        return None
    t = e.text.strip()
    return t or None


def num(el, *names) -> float | None:
    t = txt(el, *names)
    if t is None:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _bool(el, *names) -> bool | None:
    t = txt(el, *names)
    return None if t is None else t.lower() == "true"


class Parser:
    def __init__(self, codelists: Codelists):
        self.cl = codelists

    def code(self, el, *names) -> dict | None:
        e = kid(el, *names) if names else el
        if e is None or not (e.text or "").strip():
            return None
        c = e.text.strip()
        label = e.get("name") or self.cl.label(e.get("listURI"), c)
        return {"code": c, "label": label}

    # ── building blocks ────────────────────────────────────────────────────
    def _budget(self, pp) -> dict:
        b = kid(pp, "BudgetAmount")
        return {
            "value_estimated": num(b, "EstimatedOverallContractAmount"),
            "budget_tax_excl": num(b, "TaxExclusiveAmount"),
            "budget_total": num(b, "TotalAmount"),
        }

    def _cpvs(self, pp) -> list[str]:
        return [c for c in (txt(r, "ItemClassificationCode") for r in kids(pp, "RequiredCommodityClassification")) if c]

    def _location(self, pp) -> dict | None:
        loc = kid(pp, "RealizedLocation")
        if loc is None:
            return None
        return {
            "nuts": txt(loc, "CountrySubentityCode"),
            "region": txt(loc, "CountrySubentity"),
            "city": txt(loc, "Address", "CityName"),
            "postal_code": txt(loc, "Address", "PostalZone"),
        }

    def _duration(self, pp) -> dict | None:
        p = kid(pp, "PlannedPeriod")
        if p is None:
            return None
        d = kid(p, "DurationMeasure")
        return {
            "value": num(p, "DurationMeasure"),
            "unit": d.get("unitCode") if d is not None else None,
            "start": txt(p, "StartDate"),
            "end": txt(p, "EndDate"),
        }

    def _terms(self, tt, lot: str | None) -> dict:
        """TenderingTerms -> criteria, requirements, guarantees, conditions. lot=None means all lots."""
        out = {"award_criteria": [], "requirements": [], "guarantees": [], "execution_conditions": [],
               "subcontracting": None, "other": {}}
        if tt is None:
            return out
        for at in kids(tt, "AwardingTerms"):
            for ac in kids(at, "AwardingCriteria"):
                typ = txt(ac, "AwardingCriteriaTypeCode")
                out["award_criteria"].append({
                    "lot": lot,
                    "name": txt(ac, "Description"),
                    # SUBJ = juicio de valor, OBJ = fórmula
                    "kind": {"SUBJ": "judgement", "OBJ": "formula"}.get(typ or "", typ),
                    "subtype": self.code(ac, "AwardingCriteriaSubTypeCode"),
                    "points": num(ac, "WeightNumeric"),
                    "detail": txt(ac, "Note"),
                    "source": "feed",
                })
        for qr in kids(tt, "TendererQualificationRequest"):
            for tag, group in (("FinancialEvaluationCriteria", "financial"), ("TechnicalEvaluationCriteria", "technical")):
                for c in kids(qr, tag):
                    out["requirements"].append({
                        "lot": lot, "group": group,
                        "type": self.code(c, "EvaluationCriteriaTypeCode"),
                        "text": txt(c, "Description"),
                        "threshold": num(c, "ThresholdQuantity"),
                        "source": "feed",
                    })
            for c in kids(qr, "SpecificTendererRequirement"):
                out["requirements"].append({
                    "lot": lot, "group": "declaration",
                    "type": self.code(c, "RequirementTypeCode"),
                    "text": txt(c, "Description"), "threshold": None, "source": "feed",
                })
            for s in kids(qr, "RequiredBusinessClassificationScheme"):
                for cat in kids(s, "ClassificationCategory"):
                    out["requirements"].append({
                        "lot": lot, "group": "classification",
                        "type": {"code": txt(s, "ID"), "label": "Clasificación empresarial"},
                        "text": txt(cat, "CodeValue") or txt(cat, "Description"),
                        "threshold": None, "source": "feed",
                    })
            for c in kids(qr, "PersonalSituation"):
                out["requirements"].append({"lot": lot, "group": "personal_situation", "type": None,
                                            "text": txt(c, "Description") or txt(c), "threshold": None, "source": "feed"})
        for g in kids(tt, "RequiredFinancialGuarantee"):
            out["guarantees"].append({
                "lot": lot,
                "type": self.code(g, "GuaranteeTypeCode"),
                "amount": num(g, "LiabilityAmount"),
                "rate_pct": num(g, "AmountRate"),
            })
        for r in kids(tt, "ContractExecutionRequirement"):
            out["execution_conditions"].append({
                "lot": lot, "name": txt(r, "Name"),
                "type": self.code(r, "ExecutionRequirementCode"), "text": txt(r, "Description"),
            })
        st = kid(tt, "AllowedSubcontractTerms")
        if st is not None:
            out["subcontracting"] = {"text": txt(st, "Description"), "rate_pct": num(st, "Rate")}
        out["other"] = {k: v for k, v in {
            "variants_allowed": _bool(tt, "VariantConstraintIndicator"),
            "curricula_required": _bool(tt, "RequiredCurriculaIndicator"),
            "price_revision": txt(tt, "PriceRevisionFormulaDescription"),
            "funding": self.code(tt, "FundingProgramCode"),
            "national_legislation": self.code(tt, "ProcurementNationalLegislationCode"),
            "eu_legislation": [txt(x, "ID") for x in kids(tt, "ProcurementLegislationDocumentReference")] or None,
            "appeals_received": num(tt, "ReceivedAppealQuantity"),
            "language": txt(tt, "Language", "ID"),
        }.items() if v is not None}
        return out

    def _doc_ref(self, el, source: str) -> dict | None:
        ext = kid(el, "Attachment", "ExternalReference")
        url = txt(ext, "URI")
        if not url:
            return None
        type_code = self.code(el, "DocumentTypeCode")
        return {
            "source": source,
            "label": txt(ext, "FileName") or txt(el, "ID"),
            "url": url,
            "feed_hash": txt(ext, "DocumentHash"),
            "type_code": type_code["code"] if type_code else None,
            "type_label": type_code["label"] if type_code else None,
        }

    # ── whole folder ───────────────────────────────────────────────────────
    def parse_entry(self, entry, channel: str) -> dict:
        cfs = kid(entry, "ContractFolderStatus")
        link_el = entry.find(f"{ATOM}link")
        rec: dict = {
            "id": (entry.findtext(f"{ATOM}id") or "").rstrip("/").rsplit("/", 1)[-1],
            "channel": channel,
            "updated": entry.findtext(f"{ATOM}updated"),
            "link": link_el.get("href") if link_el is not None else None,
            "atom_title": entry.findtext(f"{ATOM}title"),
            "atom_summary": entry.findtext(f"{ATOM}summary"),
        }
        if cfs is None:
            return rec
        rec["folder_id"] = txt(cfs, "ContractFolderID")
        rec["status"] = self.code(cfs, "ContractFolderStatusCode")
        rec["ted_uuid"] = txt(cfs, "UUID")

        lcp = kid(cfs, "LocatedContractingParty")
        party = kid(lcp, "Party")
        hierarchy, p = [], kid(lcp, "ParentLocatedParty")
        while p is not None:
            n = txt(p, "PartyName", "Name")
            if n:
                hierarchy.append(n)
            p = kid(p, "ParentLocatedParty")
        ids = {i.get("schemeName") or "ID": i.text.strip() for i in party.iterfind(_path("PartyIdentification", "ID")) if i.text} if party is not None else {}
        rec["authority"] = {
            "name": txt(party, "PartyName", "Name"),
            "ids": ids,
            "nif": ids.get("NIF"),
            "dir3": ids.get("DIR3"),
            "platform_id": ids.get("ID_PLATAFORMA"),
            "type": self.code(lcp, "ContractingPartyTypeCode"),
            "activity": self.code(lcp, "ActivityCode"),
            "website": txt(party, "WebsiteURI"),
            "buyer_profile": txt(lcp, "BuyerProfileURIID"),
            "city": txt(party, "PostalAddress", "CityName"),
            "postal_code": txt(party, "PostalAddress", "PostalZone"),
            "hierarchy": hierarchy,
        }

        pp = kid(cfs, "ProcurementProject")
        tp = kid(cfs, "TenderingProcess")
        ext = kid(pp, "ContractExtension")
        rec["tender"] = {
            "name": txt(pp, "Name"),
            "contract_type": self.code(pp, "TypeCode"),
            "subtype": self.code(pp, "SubTypeCode"),
            "mixed": _bool(pp, "MixContractIndicator"),
            **self._budget(pp),
            "cpv": self._cpvs(pp),
            "location": self._location(pp),
            "duration": self._duration(pp),
            "extension": txt(ext, "OptionValidityPeriod", "Description") or txt(ext, "OptionsDescription"),
            "procedure": self.code(tp, "ProcedureCode"),
            "urgency": self.code(tp, "UrgencyCode"),
            "contracting_system": self.code(tp, "ContractingSystemCode"),
            "submission_method": self.code(tp, "SubmissionMethodCode"),
            "sara": _bool(tp, "OverThresholdIndicator"),
            "deadline": {
                "date": txt(tp, "TenderSubmissionDeadlinePeriod", "EndDate"),
                "time": txt(tp, "TenderSubmissionDeadlinePeriod", "EndTime"),
            },
            "doc_availability_end": txt(tp, "DocumentAvailabilityPeriod", "EndDate"),
            "auction": _bool(tp, "AuctionTerms", "AuctionConstraintIndicator"),
        }

        terms = self._terms(kid(cfs, "TenderingTerms"), None)
        lots = []
        for lot in kids(cfs, "ProcurementProjectLot"):
            lpp = kid(lot, "ProcurementProject")
            lid = txt(lot, "ID")
            lots.append({
                "number": lid,
                "name": txt(lpp, "Name"),
                "cpv": self._cpvs(lpp),
                **self._budget(lpp),
                "location": self._location(lpp),
            })
            lt = self._terms(kid(lot, "TenderingTerms"), lid)
            for k in ("award_criteria", "requirements", "guarantees", "execution_conditions"):
                terms[k].extend(lt[k])
        if not lots:
            # The data model always has at least lot 1.
            lots.append({"number": "1", "name": None, "cpv": rec["tender"]["cpv"],
                         "value_estimated": rec["tender"]["value_estimated"],
                         "budget_tax_excl": rec["tender"]["budget_tax_excl"],
                         "budget_total": rec["tender"]["budget_total"],
                         "location": rec["tender"]["location"], "implicit": True})
        rec["lots"] = lots
        rec.update({k: terms[k] for k in ("award_criteria", "requirements", "guarantees", "execution_conditions")})
        rec["subcontracting"] = terms["subcontracting"]
        rec["terms_other"] = terms["other"]

        results = []
        for tr in kids(cfs, "TenderResult"):
            atp = kid(tr, "AwardedTenderedProject")
            winners = []
            for wp in kids(tr, "WinningParty"):
                wids = {i.get("schemeName") or "ID": i.text.strip() for i in wp.iterfind(_path("PartyIdentification", "ID")) if i.text}
                winners.append({
                    "name": txt(wp, "PartyName", "Name"),
                    "nif": wids.get("NIF") or next(iter(wids.values()), None),
                    "nuts": txt(wp, "PhysicalLocation", "CountrySubentityCode"),
                    "city": txt(wp, "PhysicalLocation", "Address", "CityName"),
                })
            contracts = [{"id": txt(c, "ID"), "signed": txt(c, "IssueDate")} for c in kids(tr, "Contract")]
            results.append({
                "lots": [x.text.strip() for x in atp.iterfind(_path("ProcurementProjectLotID")) if x.text] if atp is not None else [],
                "result": self.code(tr, "ResultCode"),
                "description": txt(tr, "Description"),
                "award_date": txt(tr, "AwardDate"),
                "start_date": txt(tr, "StartDate"),
                "bids_received": num(tr, "ReceivedTenderQuantity"),
                "sme_bids": num(tr, "SMEsReceivedTenderQuantity"),
                "eu_bids": num(tr, "EUNationalsReceivedTenderQuantity"),
                "non_eu_bids": num(tr, "NonEUNationalsReceivedTenderQuantity"),
                "lowest_bid": num(tr, "LowerTenderAmount"),
                "highest_bid": num(tr, "HigherTenderAmount"),
                "abnormally_low_excluded": _bool(tr, "AbnormallyLowTendersIndicator"),
                "sme_awarded": _bool(tr, "SMEAwardedIndicator"),
                "winners": winners,
                "amount_tax_excl": num(atp, "LegalMonetaryTotal", "TaxExclusiveAmount"),
                "amount_payable": num(atp, "LegalMonetaryTotal", "PayableAmount"),
                "contracts": contracts,
            })
        rec["results"] = results

        rec["modifications"] = [{
            "id": txt(m, "ID"),
            "note": txt(m, "Note"),
            "contract_id": txt(m, "ContractID"),
            "duration_change": num(m, "ContractModificationDurationMeasure"),
            "final_duration": num(m, "FinalDurationMeasure"),
            "amount_change": num(m, "ContractModificationLegalMonetaryTotal", "TaxExclusiveAmount"),
            "final_amount": num(m, "FinalLegalMonetaryTotal", "TaxExclusiveAmount"),
        } for m in kids(cfs, "ContractModification")]

        notices, docs = [], []
        for vn in kids(cfs, "ValidNoticeInfo"):
            ntype = self.code(vn, "NoticeTypeCode")
            n = {"type": ntype, "media": [], "dates": [], "docs": []}
            for st in kids(vn, "AdditionalPublicationStatus"):
                media = txt(st, "PublicationMediaName")
                if media:
                    n["media"].append(media)
                for ref in kids(st, "AdditionalPublicationDocumentReference"):
                    d = txt(ref, "IssueDate")
                    if d:
                        n["dates"].append(d)
                    dr = self._doc_ref(ref, "feed_notice")
                    if dr:
                        dr["notice_type"] = ntype["code"] if ntype else None
                        n["docs"].append(dr)
                        docs.append(dr)
            n["published"] = min(n["dates"]) if n["dates"] else None
            notices.append(n)
        rec["notices"] = notices

        for tag, source in (("LegalDocumentReference", "feed_legal"),
                            ("TechnicalDocumentReference", "feed_technical"),
                            ("AdditionalDocumentReference", "feed_additional")):
            for el in kids(cfs, tag):
                dr = self._doc_ref(el, source)
                if dr:
                    docs.append(dr)
        for gd in kids(cfs, "GeneralDocument"):
            for el in kids(gd, "GeneralDocumentDocumentReference"):
                dr = self._doc_ref(el, "feed_general")
                if dr:
                    docs.append(dr)
        rec["documents"] = docs
        return rec


def iter_entries(path: str):
    """Yield (entry_element) for each <entry> in an ATOM file; also the next-page link."""
    tree = etree.parse(path)
    root = tree.getroot()
    nxt = None
    for l in root.findall(f"{ATOM}link"):
        if l.get("rel") == "next":
            nxt = l.get("href")
    return root.findall(f"{ATOM}entry"), nxt
