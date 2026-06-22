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
