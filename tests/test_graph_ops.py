from placsp.models import ProcurementRecord, LotResult
from placsp.graph_ops import (
    normalize_nif, normalize_name, is_ute_winner,
    record_to_graph_ops, merge_batches, GraphBatch,
)

def _rec(**kw):
    base = dict(syndication_id="100", category="placsp_mayores", updated="2025-01-01")
    base.update(kw)
    return ProcurementRecord(**base)

def test_normalize_nif():
    assert normalize_nif(" b-72.318.934 ") == "B72318934"
    assert normalize_nif("") is None
    assert normalize_nif(None) is None

def test_normalize_name_strips_legal_suffix():
    assert normalize_name("Hermanos Oliva Bahia, S.L.L.") == normalize_name("HERMANOS OLIVA BAHIA SLL")
    assert normalize_name("Acme S.A.") == "ACME"

def test_is_ute_winner():
    assert is_ute_winner("UTE LIMPIEZA 2025", "U12345678") is True
    assert is_ute_winner("UTE Algo", "B12345678") is True
    assert is_ute_winner("Acme SL", "B12345678") is False

def test_single_lot_award_produces_company_contract_lot_won():
    rec = _rec(title="Servicio X", contracting_authority="Ayto Z",
               contracting_authority_id="L01", nuts="ES61",
               lot_results=[LotResult(lot_id="0", winner_name="Acme SL",
                                      winner_nif="B12345678", amount=1000.0,
                                      award_date="2025-03-01", cpv=["45110000"])])
    b = record_to_graph_ops(rec)
    assert b.companies == [{"nif": "B12345678", "is_ute": False}]
    assert b.contracts[0]["syndication_id"] == "100"
    assert b.lots[0]["lot_key"] == "100:0"
    assert b.won[0] == {"nif": "B12345678", "lot_key": "100:0", "amount": 1000.0,
                        "award_date": "2025-03-01",
                        "name_norm": normalize_name("Acme SL"), "name_display": "Acme SL"}
    assert {"authority_id": "L01", "syndication_id": "100"} in b.tendered
    assert {"lot_key": "100:0", "cpv": "45110000"} in b.classified
    assert {"syndication_id": "100", "nuts": "ES61"} in b.located
    assert b.affected_nifs == ["B12345678"]

def test_multilot_multiwinner_distinct_won_edges():
    rec = _rec(syndication_id="200", lot_results=[
        LotResult(lot_id="1", winner_name="A SL", winner_nif="B1", amount=10.0),
        LotResult(lot_id="2", winner_name="B SL", winner_nif="B2", amount=20.0),
    ])
    b = record_to_graph_ops(rec)
    assert {c["nif"] for c in b.companies} == {"B1", "B2"}
    assert sorted(w["lot_key"] for w in b.won) == ["200:1", "200:2"]

def test_no_nif_award_skipped():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="Anon", winner_nif=None, amount=5.0)])
    b = record_to_graph_ops(rec)
    assert b.companies == []
    assert b.won == []
    # contract with no graphable winner is not emitted either
    assert b.contracts == []

def test_lot_bid_stats_on_lot_dict():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="A", winner_nif="B1",
                                      n_bids=3, n_sme_bids=1,
                                      lower_tender_amount=9.0, higher_tender_amount=11.0)])
    b = record_to_graph_ops(rec)
    lot = b.lots[0]
    assert lot["n_bids"] == 3 and lot["n_sme_bids"] == 1
    assert lot["lower_tender_amount"] == 9.0 and lot["higher_tender_amount"] == 11.0

def test_ute_company_flagged():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="UTE X", winner_nif="U99999999", amount=1.0)])
    b = record_to_graph_ops(rec)
    assert b.companies == [{"nif": "U99999999", "is_ute": True}]

def test_merge_batches_concatenates():
    r1 = record_to_graph_ops(_rec(syndication_id="1",
            lot_results=[LotResult(lot_id="0", winner_nif="B1", winner_name="A", amount=1.0)]))
    r2 = record_to_graph_ops(_rec(syndication_id="2",
            lot_results=[LotResult(lot_id="0", winner_nif="B2", winner_name="C", amount=2.0)]))
    m = merge_batches([r1, r2])
    assert len(m.won) == 2
    assert {c["nif"] for c in m.companies} == {"B1", "B2"}
