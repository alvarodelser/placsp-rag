from placsp.models import ProcurementRecord, Lot, StatusEvent

def test_record_minimal_and_defaults():
    r = ProcurementRecord(syndication_id="19862167", category="placsp_mayores", updated="2026-06-19T21:50:27+02:00")
    assert r.cpv == [] and r.lots == [] and r.status_history == []
    assert r.lang == "es"
    assert r.budget_amount is None

def test_lot_and_status():
    lot = Lot(lot_id="1", name="Obra", amount=100.0, cpv=["45000000"])
    ev = StatusEvent(code="ADJ", date="2026-05-20")
    assert lot.cpv == ["45000000"] and ev.code == "ADJ"
