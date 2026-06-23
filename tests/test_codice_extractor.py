from placsp.atom_parser import parse_feed
from placsp.codice_extractor import extract, first_text, NS
from placsp.codelists import Codelists
from placsp.models import RawEntry

def _first_entry(path, cat):
    for it in parse_feed(path, cat):
        if isinstance(it, RawEntry):
            return it

def test_identity_and_classification_mayores():
    raw = _first_entry("tests/fixtures/mayores.atom", "placsp_mayores")
    cl = Codelists("tests/fixtures")
    rec = extract(raw, cl)
    assert rec.syndication_id.isdigit()
    assert rec.category == "placsp_mayores"
    assert rec.title and rec.expediente            # expediente = ContractFolderID
    assert rec.status_code in {"PUB","EV","ADJ","RES","PRE"}
    assert rec.contracting_authority               # órgano name present
    assert rec.contract_type_code is not None

def test_contract_type_decoded_when_codelist_present():
    # propios fixture has TypeCode; ContractCode.gc decodes 1->Suministros etc.
    raw = _first_entry("tests/fixtures/propios.atom", "propios")
    rec = extract(raw, Codelists("tests/fixtures"))
    if rec.contract_type_code in {"1","2","3"}:
        assert rec.contract_type  # decoded label or raw fallback, never empty when code present

def test_extract_without_codelists_does_not_crash():
    raw = _first_entry("tests/fixtures/menores.atom", "placsp_menores")
    rec = extract(raw, None)
    assert rec.syndication_id and rec.status_code

def test_money_source_paths():
    # menores: amount lives under TenderResult; always awarded
    raw = _first_entry("tests/fixtures/menores.atom", "placsp_menores")
    rec = extract(raw, None)
    assert rec.awarded_amount is not None and rec.awarded_amount > 0
    assert rec.result_code is not None
    assert rec.adjudicatario  # winner name

def test_budget_present_for_propios():
    raw = _first_entry("tests/fixtures/propios.atom", "propios")
    rec = extract(raw, None)
    assert rec.budget_amount is not None

def test_lot_results_multilot_mayores():
    # mayores sid 17200541 has 3 TenderResults, one per ProcurementProjectLot,
    # all won by HERMANOS OLIVA BAHIA SLL (B72318934)
    cl = Codelists("tests/fixtures")
    rec = None
    for it in parse_feed("tests/fixtures/mayores.atom", "placsp_mayores"):
        if isinstance(it, RawEntry) and it.syndication_id == "17200541":
            rec = extract(it, cl); break
    assert rec is not None
    assert len(rec.lot_results) == 3
    lot_ids = sorted(lr.lot_id for lr in rec.lot_results)
    assert lot_ids == ["1", "2", "3"]
    for lr in rec.lot_results:
        assert lr.winner_nif == "B72318934"
        assert lr.winner_name == "HERMANOS OLIVA BAHIA SLL"
        assert lr.amount is not None and lr.amount > 0

def test_lot_results_bid_stats_present_mayores():
    cl = Codelists("tests/fixtures")
    rec = next(extract(it, cl) for it in parse_feed("tests/fixtures/mayores.atom", "placsp_mayores")
               if isinstance(it, RawEntry) and it.syndication_id == "17200541")
    lr = rec.lot_results[0]
    assert lr.n_bids is not None and lr.n_bids >= 1
    # mayores carries SMEsReceivedTenderQuantity + Lower/HigherTenderAmount
    assert lr.lower_tender_amount is not None
    assert lr.higher_tender_amount is not None

def test_lot_results_implicit_single_lot_menores():
    # menores have a TenderResult + WinningParty but no ProcurementProjectLot
    rec = next(extract(it, None) for it in parse_feed("tests/fixtures/menores.atom", "placsp_menores")
               if isinstance(it, RawEntry))
    assert len(rec.lot_results) == 1
    lr = rec.lot_results[0]
    assert lr.lot_id == "0"
    assert lr.winner_name  # winner present
    assert lr.amount is not None and lr.amount > 0

def test_existing_weaviate_fields_unchanged_menores():
    # Regression: the existing record-level fields the Weaviate path uses must remain
    rec = next(extract(it, None) for it in parse_feed("tests/fixtures/menores.atom", "placsp_menores")
               if isinstance(it, RawEntry))
    assert rec.adjudicatario and rec.adjudicatario_nif
    assert rec.awarded_amount is not None
