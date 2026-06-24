import atexit
import os

from fastapi import APIRouter, HTTPException, Query
from neo4j import GraphDatabase

router = APIRouter(prefix="/api/graph", tags=["graph"])

NEO4J_URL = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        if not NEO4J_PASSWORD:
            raise HTTPException(503, "Neo4j not configured — set NEO4J_PASSWORD to enable graph endpoints")
        _driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


@atexit.register
def _close_driver():
    if _driver is not None:
        _driver.close()

@router.get("/company/{nif}")
def get_company(nif: str):
    """Get company profile and aggregate statistics."""
    cypher = """
    MATCH (c:Company {nif: $nif})
    OPTIONAL MATCH (c)-[w:WON]->(lo:Lot)<-[:HAS_LOT]-(ct:Contract)
    WITH c, w, lo, ct
    OPTIONAL MATCH (lo)-[:CLASSIFIED_AS]->(cpv:Cpv)
    OPTIONAL MATCH (au:Authority)-[:TENDERED]->(ct)
    
    WITH c,
         count(DISTINCT ct) as total_contracts_won,
         count(DISTINCT lo) as total_lots_won,
         sum(w.amount) as total_awarded_eur,
         collect(DISTINCT {code: cpv.code}) as all_cpv,
         collect(DISTINCT {id: au.id, name: au.name}) as all_au
         
    RETURN c.nif AS nif, c.canonical_name AS canonical_name, c.is_ute AS is_ute,
           total_contracts_won, total_lots_won, total_awarded_eur,
           size(all_cpv) as unique_cpv_count, size(all_au) as unique_authorities_count
    """
    
    with get_driver().session() as session:
        result = session.run(cypher, nif=nif).single()
        if not result:
            raise HTTPException(404, "Company not found in graph")
            
        return {
            "nif": result["nif"],
            "canonical_name": result["canonical_name"],
            "is_ute": result["is_ute"],
            "stats": {
                "total_contracts_won": result["total_contracts_won"],
                "total_lots_won": result["total_lots_won"],
                "total_awarded_eur": result["total_awarded_eur"],
            },
            "unique_cpv_count": result["unique_cpv_count"],
            "unique_authorities_count": result["unique_authorities_count"],
        }

@router.get("/company/{nif}/contracts")
def get_company_contracts(nif: str, limit: int = Query(15, ge=1, le=50), offset: int = Query(0, ge=0)):
    """List contracts won by a company."""
    cypher = """
    MATCH (c:Company {nif: $nif})-[w:WON]->(lo:Lot)<-[:HAS_LOT]-(ct:Contract)
    OPTIONAL MATCH (au:Authority)-[:TENDERED]->(ct)
    RETURN ct.syndication_id AS syndication_id, ct.title AS title, 
           ct.budget_amount AS budget_amount_eur, ct.award_date AS award_date,
           au.id AS authority_id, au.name AS authority_name,
           w.amount AS won_amount_eur
    ORDER BY ct.award_date DESC
    SKIP $offset LIMIT $limit
    """
    
    count_cypher = "MATCH (:Company {nif: $nif})-[:WON]->(:Lot)<-[:HAS_LOT]-(ct:Contract) RETURN count(DISTINCT ct) AS total"
    
    with get_driver().session() as session:
        count_res = session.run(count_cypher, nif=nif).single()
        total = count_res["total"] if count_res else 0
        
        results = []
        for record in session.run(cypher, nif=nif, limit=limit, offset=offset):
            results.append({
                "syndication_id": record["syndication_id"],
                "title": record["title"],
                "budget_amount_eur": record["budget_amount_eur"],
                "award_date": record["award_date"],
                "authority_id": record["authority_id"],
                "authority_name": record["authority_name"],
                "won_amount_eur": record["won_amount_eur"],
            })
            
        return {
            "nif": nif,
            "total": total,
            "offset": offset,
            "results": results
        }

@router.get("/contract/{syndication_id}")
def get_contract_graph(syndication_id: str):
    """Get the graph neighbourhood for a specific contract."""
    cypher = """
    MATCH (ct:Contract {syndication_id: $sid})
    OPTIONAL MATCH (au:Authority)-[:TENDERED]->(ct)
    OPTIONAL MATCH (ct)-[:LOCATED_IN]->(nu:Nuts)
    OPTIONAL MATCH (ct)-[:HAS_LOT]->(lo:Lot)
    OPTIONAL MATCH (co:Company)-[w:WON]->(lo)
    OPTIONAL MATCH (lo)-[:CLASSIFIED_AS]->(cpv:Cpv)
    
    WITH ct, au, nu, lo, w, co, collect(DISTINCT cpv.code) as cpvs
    
    RETURN ct.syndication_id AS syndication_id, ct.title AS title, ct.budget_amount AS budget_amount_eur,
           ct.award_date AS award_date,
           au.id AS authority_id, au.name AS authority_name, au.org_top_level AS org_top_level,
           nu.code AS nuts_code,
           collect({
               lot_key: lo.lot_key, 
               name: lo.name, 
               amount_eur: lo.amount, 
               n_bids: lo.n_bids,
               winner_nif: co.nif,
               winner_name: co.canonical_name,
               cpv: cpvs
           }) AS lots
    """
    
    with get_driver().session() as session:
        result = session.run(cypher, sid=syndication_id).single()
        if not result or not result["syndication_id"]:
            raise HTTPException(404, "Contract not found in graph")
            
        lots_data = [l for l in result["lots"] if l["lot_key"]]
        
        return {
            "syndication_id": result["syndication_id"],
            "title": result["title"],
            "budget_amount_eur": result["budget_amount_eur"],
            "award_date": result["award_date"],
            "authority": {
                "id": result["authority_id"],
                "name": result["authority_name"],
                "org_top_level": result["org_top_level"]
            } if result["authority_id"] else None,
            "nuts": result["nuts_code"],
            "lots": lots_data
        }

@router.get("/similar/companies/{nif}")
def get_similar_companies(nif: str, limit: int = Query(10, ge=1, le=50)):
    """Find similar companies based on shared CPV categories."""
    cypher = """
    MATCH (a:Company {nif: $nif})-[:WON]->(:Lot)-[:CLASSIFIED_AS]->(cpv:Cpv)
    MATCH (lo2:Lot)-[:CLASSIFIED_AS]->(cpv)<-[:CLASSIFIED_AS]-(lo3:Lot)
    MATCH (b:Company)-[:WON]->(lo2)
    WHERE b.nif <> $nif
    WITH b, count(DISTINCT cpv) AS shared_cpv, count(DISTINCT lo2) AS shared_lots
    RETURN b.nif AS nif, b.canonical_name AS canonical_name, b.is_ute AS is_ute, 
           shared_cpv, shared_lots
    ORDER BY shared_lots DESC LIMIT $limit
    """
    
    with get_driver().session() as session:
        results = []
        for record in session.run(cypher, nif=nif, limit=limit):
            results.append({
                "nif": record["nif"],
                "canonical_name": record["canonical_name"],
                "is_ute": record["is_ute"],
                "shared_cpv_count": record["shared_cpv"],
                "shared_lots_count": record["shared_lots"],
            })
            
        return {
            "nif": nif,
            "similar_companies": results
        }
