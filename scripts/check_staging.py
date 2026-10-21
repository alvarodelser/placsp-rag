"""Check the staging parser on real archives: nothing unread, nothing lost against the old parsers.

For a sample of entries of each archive (every Nth entry, up to --max per archive):
1. unread: every element path that carries a value but that staging's parser never touched
   (found by recording what codice.kid/kids return while flattening the entry);
2. app parity: every value the app's former extractor (parsers/codice_extractor.py, removed; put
   it and core/models.py from git on PYTHONPATH as old_extractor.py and old_models.py to run it)
   gives is present in staging's rows for the same entry;
3. pilot parity: every item the pilot's parser (pilot/placsp_pilot/codice.py) gives is present in
   staging's rows.

Usage: python scripts/check_staging.py data/zips/*/*.zip [--every 7] [--max 3000] [--out FILE]
"""
import argparse, collections, json, os, sys, zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "pilot")]

from placsp.staging import codice                                   # noqa: E402
try:    # the app's former extractor, removed once staging replaced it; restore it from git to rerun 2.
    from old_models import RawEntry                                 # noqa: E402
    from old_extractor import extract as app_extract               # noqa: E402
except ImportError:
    app_extract = None
from placsp_pilot.codice import Parser as PilotParser               # noqa: E402
from placsp_pilot.codelists import Codelists as PilotCodelists      # noqa: E402

# Element paths read on purpose by nothing: presentation-only or redundant with a field we keep.
SKIPPED = {
    "LocatedContractingParty/Party/PostalAddress/Country/Name",          # country code is kept
    "ProcurementProject/RealizedLocation/Address/Country/Name",
    "ProcurementProjectLot/ProcurementProject/RealizedLocation/Address/Country/Name",
    "TenderResult/WinningParty/PhysicalLocation/Address/Country/Name",
    "LocatedContractingParty/Party/Contact/Telefax",
}


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _rel(el, root):
    parts = []
    while el is not None and el is not root:
        parts.append(_local(el.tag))
        el = el.getparent()
    return "/".join(reversed(parts))


class Recorder:
    """Wraps codice.kid/kids so every element they hand back is remembered."""
    def __init__(self):
        self.seen = set()
        self.keep = []      # lxml hands out a new proxy per access; holding them keeps their ids stable
        self._kid, self._kids = codice.kid, codice.kids

    def __enter__(self):
        def kid(el, *names):
            r = self._kid(el, *names)
            if r is not None:
                self.keep.append(r)
                self.seen.add(id(r))
            return r

        def kids(el, *names):
            r = self._kids(el, *names)
            self.keep += r
            self.seen.update(id(x) for x in r)
            return r
        codice.kid, codice.kids = kid, kids
        return self

    def __exit__(self, *a):
        codice.kid, codice.kids = self._kid, self._kids


def _norm(p):
    while "ParentLocatedParty/ParentLocatedParty" in p:
        p = p.replace("ParentLocatedParty/ParentLocatedParty", "ParentLocatedParty")
    return p


def _num_eq(a, b):
    return a is None or (b is not None and abs(float(a) - float(b)) < 1e-6)


def app_parity(rec, rows, miss):
    t = rows["entry"][0]
    lot_cpv = {c for l in rows["lot"] for c in l["cpv"]}
    auth_ids = {i.split(":", 1)[1] for i in t.get("auth_ids") or []}
    winners = [w for w in rows["winner"]]
    checks = {
        "expediente": rec.expediente == t.get("folder_id"),
        "title": rec.title == t.get("name"),
        "status_code": rec.status_code == t.get("status_code"),
        "contract_type_code": rec.contract_type_code == t.get("contract_type_code"),
        "cpv": set(rec.cpv) <= set(t.get("cpv") or []) | lot_cpv,
        "procedure_code": rec.procedure_code == t.get("procedure_code"),
        "notice_type": rec.notice_type is None or rec.notice_type in {n["type_code"] for n in rows["notice"]},
        "contracting_authority": rec.contracting_authority == t.get("auth_name"),
        "contracting_authority_id": rec.contracting_authority_id is None or rec.contracting_authority_id in auth_ids,
        "org_top_level": rec.org_top_level is None or rec.org_top_level == (t.get("auth_parent_names") or [None])[-1],
        "buyer_profile_url": rec.buyer_profile_url == t.get("auth_buyer_profile"),
        "nuts": rec.nuts == t.get("nuts"),
        "city": rec.city == t.get("auth_city"),
        "publication_date": rec.publication_date is None or rec.publication_date in {d for n in rows["notice"] for d in n["dates"]},
        "submission_deadline": rec.submission_deadline is None or rec.submission_deadline in
            {t.get("deadline_date"), t.get("participation_deadline_date")},
        "funding_program": rec.funding_program is None or rec.funding_program in (t.get("funding_codes") or []),
        "document_urls": set(rec.document_urls) <= {d["url"] for d in rows["document"]},
        "budget_amount": _num_eq(rec.budget_amount, t.get("budget_tax_excl") if t.get("budget_tax_excl") is not None else t.get("budget_total")),
        "estimated_value": _num_eq(rec.estimated_value, t.get("value_estimated")),
        "awarded_amount": rec.awarded_amount is None or any(_num_eq(rec.awarded_amount, r["amount_tax_excl"]) or
                                                            _num_eq(rec.awarded_amount, r["amount_payable"]) for r in rows["result"]),
        "result_code": rec.result_code is None or rec.result_code in {r["result_code"] for r in rows["result"]},
        "award_date": rec.award_date is None or rec.award_date in {r["award_date"] for r in rows["result"]},
        "adjudicatario": rec.adjudicatario is None or rec.adjudicatario in {w["name"] for w in winners},
        "adjudicatario_nif": rec.adjudicatario_nif is None or rec.adjudicatario_nif in {w["nif"] for w in winners},
        "n_bids": rec.n_bids is None or any(_num_eq(rec.n_bids, r["bids_received"]) for r in rows["result"]),
        "sme_awarded": rec.sme_awarded is None or rec.sme_awarded in {r["sme_awarded"] for r in rows["result"]},
        "lots": {(l.lot_id, l.name) for l in rec.lots} <= {(l["lot_id"] or "", l["name"]) for l in rows["lot"]},
        "lot_results": len(rec.lot_results) == len(rows["result"]) and all(
            (lr.winner_nif is None or lr.winner_nif in {w["nif"] for w in winners}) and
            any(_num_eq(lr.n_bids, r["bids_received"]) and _num_eq(lr.lower_tender_amount, r["lowest_bid"]) and
                _num_eq(lr.higher_tender_amount, r["highest_bid"]) and _num_eq(lr.n_sme_bids, r["sme_bids"])
                for r in rows["result"]) for lr in rec.lot_results),
    }
    for k, ok in checks.items():
        if not ok:
            miss[k] += 1


def pilot_parity(p, rows, miss):
    crit = {(c["lot_id"], c["description"], c["weight"]) for c in rows["criterion"]}
    req_texts = {(r["lot_id"], r["description"]) for r in rows["requirement"]} | \
                {(r["lot_id"], r["classification"]) for r in rows["requirement"]}
    checks = {
        "award_criteria": all((c["lot"], c["name"], c["points"]) in crit for c in p.get("award_criteria", [])),
        "requirements": all((r["lot"], r["text"]) in req_texts for r in p.get("requirements", [])),
        "guarantees": len(p.get("guarantees", [])) == len(rows["guarantee"]),
        "execution_conditions": len(p.get("execution_conditions", [])) == len(rows["condition"]),
        "results": len(p.get("results", [])) == len(rows["result"]),
        "winners": sum(len(r["winners"]) for r in p.get("results", [])) == len(rows["winner"]),
        "modifications": len(p.get("modifications", [])) == len(rows["modification"]),
        "notices": len(p.get("notices", [])) == len(rows["notice"]),
        "documents": {d["url"] for d in p.get("documents", [])} <= {d["url"] for d in rows["document"]},
        "lots": {l["number"] for l in p.get("lots", []) if not l.get("implicit")} == {l["lot_id"] for l in rows["lot"]},
        "authority_hierarchy": (p.get("authority") or {}).get("hierarchy", []) == [n for n in rows["entry"][0].get("auth_parent_names", []) if n],
        "subcontracting": (p.get("subcontracting") or {}).get("text") == rows["entry"][0].get("subcontract_text"),
    }
    for k, ok in checks.items():
        if not ok:
            miss[k] += 1


def check(zpath, every, cap, pilot_cl):
    channel = os.path.basename(os.path.dirname(zpath))
    unread, sample = collections.Counter(), {}
    app_miss, pilot_miss = collections.Counter(), collections.Counter()
    n = checked = 0
    pilot = PilotParser(pilot_cl)
    with zipfile.ZipFile(zpath) as zf:
        for member in sorted(x for x in zf.namelist() if x.endswith(".atom")):
            with zf.open(member) as fh:
                for kind, el in codice.iter_feed(fh):
                    if kind != "entry":
                        continue
                    n += 1
                    if n % every or checked >= cap:
                        continue
                    checked += 1
                    rows = codice.empty()
                    with Recorder() as rec:
                        codice.flatten(el, "k", channel, "z", member, rows)
                    cfs = codice.kid(el, "ContractFolderStatus")
                    if cfs is None:
                        continue
                    for d in cfs.iter():
                        if not isinstance(d.tag, str) or d is cfs or not (d.text or "").strip():
                            continue
                        if id(d) not in rec.seen:
                            p = _norm(_rel(d, cfs))
                            if p not in SKIPPED:
                                unread[p] += 1
                                sample.setdefault(p, d.text.strip()[:80])
                    sid = codice.entry_id(el.findtext("{http://www.w3.org/2005/Atom}id"))
                    if app_extract is not None:
                        app_parity(app_extract(RawEntry(sid, None, None, cfs, channel), None), rows, app_miss)
                    pilot_parity(pilot.parse_entry(el, channel), rows, pilot_miss)
            if checked >= cap:
                break
    return {"zip": os.path.basename(zpath), "entries_read": n, "checked": checked,
            "unread": {p: [c, sample[p]] for p, c in unread.most_common()},
            "app_mismatch": dict(app_miss), "pilot_mismatch": dict(pilot_miss)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("zips", nargs="+")
    ap.add_argument("--every", type=int, default=7)
    ap.add_argument("--max", type=int, default=3000)
    ap.add_argument("--out", default="data/survey/check_staging.json")
    a = ap.parse_args()
    cl = PilotCodelists(os.path.join(REPO, "codelists"))
    results = []
    for z in a.zips:
        r = check(z, a.every, a.max, cl)
        results.append(r)
        print(f"{r['zip']}: checked {r['checked']} | unread paths {len(r['unread'])} | "
              f"app mismatches {r['app_mismatch'] or 0} | pilot mismatches {r['pilot_mismatch'] or 0}")
        for p, (c, s) in list(r["unread"].items())[:15]:
            print(f"   unread {c:5d}  {p} | {s}")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
