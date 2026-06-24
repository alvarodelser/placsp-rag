import os
import pytest
from placsp.models import ProcurementRecord, LotResult, Tombstone
from placsp.graph_sink import GraphSink

URI = os.getenv("NEO4J_TEST_URL")
USER = os.getenv("NEO4J_TEST_USER", "neo4j")
PWD = os.getenv("NEO4J_TEST_PASSWORD", "testpassword")

pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_TEST_URL not set")

def _rec(sid, lot_results, **kw):
    base = dict(syndication_id=sid, category="placsp_mayores", updated="2025-01-01",
                title="T", contracting_authority="Auth", contracting_authority_id="L1",
                nuts="ES61", lot_results=lot_results)
    base.update(kw)
    return ProcurementRecord(**base)

@pytest.fixture
def sink():
    s = GraphSink(URI, USER, PWD)
    s.ensure_constraints()
    with s._driver.session() as ses:
        ses.run("MATCH (n) DETACH DELETE n")
    yield s
    s.close()

def _count(sink, cypher):
    with sink._driver.session() as ses:
        return ses.run(cypher).single()[0]

def test_upsert_creates_nodes_and_is_idempotent(sink):
    rec = _rec("100", [LotResult(lot_id="1", winner_name="Acme SL", winner_nif="B1",
                                 amount=10.0, cpv=["45110000"],
                                 n_bids=3, lower_tender_amount=9.0)])
    sink.upsert([rec])
    sink.upsert([rec])  # second run must not duplicate
    assert _count(sink, "MATCH (c:Company) RETURN count(c)") == 1
    assert _count(sink, "MATCH (:Company)-[w:WON]->(:Lot) RETURN count(w)") == 1
    assert _count(sink, "MATCH (:Contract)-[h:HAS_LOT]->(:Lot) RETURN count(h)") == 1
    assert _count(sink, "MATCH (:Lot)-[r:CLASSIFIED_AS]->(:Cpv) RETURN count(r)") == 1
    # Bid-stat fields must persist on the Lot node (guards the lots-Cypher correction)
    assert _count(sink, "MATCH (l:Lot {lot_key:'100:1'}) RETURN l.n_bids") == 3
    assert _count(sink, "MATCH (l:Lot {lot_key:'100:1'}) RETURN l.lower_tender_amount") == 9.0

def test_canonical_name_is_most_frequent(sink):
    # Same NIF wins two lots as "Acme SL" and one as "ACME, S.L." → display of the
    # most frequent NORMALIZED form wins.
    sink.upsert([_rec("1", [LotResult(lot_id="0", winner_name="Acme SL", winner_nif="B9", amount=1.0)])])
    sink.upsert([_rec("2", [LotResult(lot_id="0", winner_name="Acme SL", winner_nif="B9", amount=1.0)])])
    sink.upsert([_rec("3", [LotResult(lot_id="0", winner_name="OTHERNAME SA", winner_nif="B9", amount=1.0)])])
    name = _count(sink, "MATCH (c:Company {nif:'B9'}) RETURN c.canonical_name")
    assert name == "Acme SL"

def test_tombstone_deletes_contract_and_lots_keeps_company(sink):
    sink.upsert([_rec("500", [LotResult(lot_id="1", winner_name="Acme", winner_nif="B1", amount=5.0)])])
    sink.apply_tombstones([Tombstone(syndication_id="500", when=None, reason="CERRADA",
                                     category="placsp_mayores")])
    assert _count(sink, "MATCH (c:Contract {syndication_id:'500'}) RETURN count(c)") == 0
    assert _count(sink, "MATCH (l:Lot {lot_key:'500:1'}) RETURN count(l)") == 0
    assert _count(sink, "MATCH (c:Company {nif:'B1'}) RETURN count(c)") == 1
