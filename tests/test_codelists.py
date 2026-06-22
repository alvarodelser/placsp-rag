from placsp.codelists import parse_gc, Codelists

def test_parse_gc_contract_code():
    m = parse_gc("tests/fixtures/ContractCode.gc")
    assert m["1"] == "Suministros"            # verified from real .gc
    assert len(m) >= 3

def test_codelists_label_and_graceful_miss():
    cl = Codelists("tests/fixtures")
    assert cl.label("https://x/codice/cl/2.08/ContractCode-2.08.gc", "1") is None  # filename != fixture name
    cl2 = Codelists("tests/fixtures")
    assert cl2.label("https://x/whatever/ContractCode.gc", "1") == "Suministros"
    assert cl2.label("https://x/ContractCode.gc", "999") is None
    assert cl2.label(None, "1") is None
