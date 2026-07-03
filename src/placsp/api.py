from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import httpx
import json
from typing import Dict, Any

from placsp.config import load_config
from placsp.parsers.pliego_html_parser import PliegoHTMLParser
import structlog

log = structlog.get_logger()
app = FastAPI(title="Placsp Ingester API")

# Load configuration
cfg = load_config()

def _get_licitacion(syndication_id: str) -> Dict[str, Any]:
    """Fetch the licitacion object from Weaviate."""
    where = f'{{ path: ["syndication_id"], operator: Equal, valueText: {json.dumps(syndication_id)} }}'
    gql = f"{{ Get {{ Placsp_licitaciones(where: {where}) {{ syndication_id expediente source_url }} }} }}"
    
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql", json={"query": gql}, headers=headers)
    r.raise_for_status()
    
    data = r.json().get('data', {}).get('Get', {}).get('Placsp_licitaciones', [])
    if not data:
        raise ValueError(f"No licitación found with syndication_id {syndication_id}")
    return data[0]

class AnalyzeRequest(BaseModel):
    user_id: str
    item_id: str

@app.post("/internal/analyze/{syndication_id}")
def trigger_analysis(syndication_id: str, body: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Triggers the async Tier 2 analysis."""
    background_tasks.add_task(run_nlp_pipeline, syndication_id, body.user_id, body.item_id)
    return {"status": "accepted", "message": "Analysis queued"}

def run_nlp_pipeline(syndication_id: str, user_id: str, item_id: str):
    """Background task to run the NLP pipeline."""
    from placsp.ai.nlp_pipeline import NLPPipeline

    nlp = NLPPipeline(cfg)
    try:
        # 1. Fetch licitacion metadata to get the source URL
        lic = _get_licitacion(syndication_id)
        source_url = lic.get('source_url')
        if not source_url or "contrataciondelestado.es" not in source_url:
            log.warning("nlp_skipped_no_url", syndication_id=syndication_id)
            nlp.mark_failed(user_id, item_id, "no analizable: sin URL de detalle")
            return

        # 2. Fetch and parse criteria from the source HTML
        r = httpx.get(source_url, follow_redirects=True)
        r.raise_for_status()
        parser = PliegoHTMLParser(r.text)
        criteria = parser.parse()

        # 3. Run Pipeline
        nlp.run_pipeline(syndication_id, user_id, item_id, criteria.__dict__)
    except Exception as e:
        log.error("nlp_pipeline_failed", syndication_id=syndication_id, error=str(e))
        nlp.mark_failed(user_id, item_id, str(e))
