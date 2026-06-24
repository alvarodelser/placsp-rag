import structlog
from neo4j import GraphDatabase
from .models import ProcurementRecord, Tombstone
from .graph_ops import record_to_graph_ops, merge_batches, GraphBatch

log = structlog.get_logger(service="placsp")

_CONSTRAINTS = [
    "CREATE CONSTRAINT company_nif IF NOT EXISTS FOR (c:Company) REQUIRE c.nif IS UNIQUE",
    "CREATE CONSTRAINT contract_sid IF NOT EXISTS FOR (c:Contract) REQUIRE c.syndication_id IS UNIQUE",
    "CREATE CONSTRAINT lot_key IF NOT EXISTS FOR (l:Lot) REQUIRE l.lot_key IS UNIQUE",
    "CREATE CONSTRAINT authority_id IF NOT EXISTS FOR (a:Authority) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT cpv_code IF NOT EXISTS FOR (c:Cpv) REQUIRE c.code IS UNIQUE",
    "CREATE CONSTRAINT nuts_code IF NOT EXISTS FOR (n:Nuts) REQUIRE n.code IS UNIQUE",
]

_WRITE = [
    ("UNWIND $companies AS c MERGE (co:Company {nif:c.nif}) "
     "ON CREATE SET co.is_ute=c.is_ute ON MATCH SET co.is_ute = co.is_ute OR c.is_ute", "companies"),
    ("UNWIND $contracts AS k MERGE (ct:Contract {syndication_id:k.syndication_id}) SET ct += k.props",
     "contracts"),
    # Corrected lots write: bid-stat fields are top-level in the dict, NOT inside props.
    # SET lo += l.props covers name/amount/award_date/sme_awarded;
    # the four bid-stat fields are set explicitly from their top-level keys.
    ("UNWIND $lots AS l MERGE (lo:Lot {lot_key:l.lot_key}) "
     "SET lo += l.props, "
     "    lo.n_bids = l.n_bids, lo.n_sme_bids = l.n_sme_bids, "
     "    lo.lower_tender_amount = l.lower_tender_amount, lo.higher_tender_amount = l.higher_tender_amount "
     "WITH l, lo MATCH (ct:Contract {syndication_id:l.syndication_id}) MERGE (ct)-[:HAS_LOT]->(lo)",
     "lots"),
    ("UNWIND $won AS w MATCH (co:Company {nif:w.nif}), (lo:Lot {lot_key:w.lot_key}) "
     "MERGE (co)-[r:WON]->(lo) "
     "SET r.amount=w.amount, r.award_date=w.award_date, r.name_norm=w.name_norm, r.name_display=w.name_display",
     "won"),
    ("UNWIND $authorities AS a MERGE (au:Authority {id:a.id}) SET au.name=a.name, au.org_top_level=a.org_top_level",
     "authorities"),
    ("UNWIND $tendered AS t MATCH (au:Authority {id:t.authority_id}), (ct:Contract {syndication_id:t.syndication_id}) "
     "MERGE (au)-[:TENDERED]->(ct)", "tendered"),
    ("UNWIND $classified AS x MERGE (cp:Cpv {code:x.cpv}) "
     "WITH x, cp MATCH (lo:Lot {lot_key:x.lot_key}) MERGE (lo)-[:CLASSIFIED_AS]->(cp)", "classified"),
    ("UNWIND $located AS n MERGE (nu:Nuts {code:n.nuts}) "
     "WITH n, nu MATCH (ct:Contract {syndication_id:n.syndication_id}) MERGE (ct)-[:LOCATED_IN]->(nu)", "located"),
    ("UNWIND $affected_nifs AS nif MATCH (co:Company {nif:nif})-[r:WON]->(:Lot) "
     "WITH co, r.name_norm AS norm, collect(r.name_display)[0] AS disp, count(*) AS n "
     "ORDER BY n DESC, norm WITH co, collect(disp)[0] AS top SET co.canonical_name = top", "affected_nifs"),
]


class GraphSink:
    def __init__(self, uri, user, password):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def ensure_constraints(self):
        with self._driver.session() as s:
            for stmt in _CONSTRAINTS:
                s.run(stmt)

    @staticmethod
    def _apply(tx, batch: GraphBatch):
        params = {
            "companies": batch.companies, "contracts": batch.contracts, "lots": batch.lots,
            "won": batch.won, "authorities": batch.authorities, "tendered": batch.tendered,
            "classified": batch.classified, "located": batch.located,
            "affected_nifs": list(dict.fromkeys(batch.affected_nifs)),
        }
        for cypher, key in _WRITE:
            if params.get(key):
                tx.run(cypher, **params)

    def upsert(self, records: list[ProcurementRecord]) -> int:
        batch = merge_batches([record_to_graph_ops(r) for r in records])
        if not batch.won:
            return 0
        with self._driver.session() as s:
            s.execute_write(self._apply, batch)
        log.info("graph_upserted", companies=len(batch.companies), won=len(batch.won))
        return len(batch.won)

    def apply_tombstones(self, tombs: list[Tombstone]) -> int:
        if not tombs:
            return 0
        sids = [t.syndication_id for t in tombs]
        with self._driver.session() as s:
            s.run("UNWIND $sids AS sid MATCH (ct:Contract {syndication_id:sid}) "
                  "OPTIONAL MATCH (ct)-[:HAS_LOT]->(lo:Lot) DETACH DELETE lo, ct", sids=sids)
        return len(tombs)
