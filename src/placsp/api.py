from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import httpx
import json
from typing import Dict, Any

from placsp.config import load_config
import structlog

log = structlog.get_logger()
app = FastAPI(title="Placsp Ingester API")

# Load configuration
cfg = load_config()

def _get_criteria(syndication_id: str) -> Dict[str, Any] | None:
    """The tender's platform criteria (pdf_links included), loaded from the staging tables."""
    where = f'{{ path: ["syndication_id"], operator: Equal, valueText: {json.dumps(syndication_id)} }}'
    gql = f"{{ Get {{ Placsp_pliego_criteria(where: {where}) {{ criteria_json }} }} }}"
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql", json={"query": gql}, headers=headers)
    r.raise_for_status()
    hits = (r.json().get("data") or {}).get("Get", {}).get("Placsp_pliego_criteria") or []
    return json.loads(hits[0]["criteria_json"] or "{}") if hits else None

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
        criteria = _get_criteria(syndication_id)
        if not criteria or not criteria.get("pdf_links"):
            log.warning("nlp_skipped_no_documents", syndication_id=syndication_id)
            nlp.mark_failed(user_id, item_id, "no analizable: la licitación no publica pliegos")
            return
        nlp.run_pipeline(syndication_id, user_id, item_id, criteria)
    except Exception as e:
        log.error("nlp_pipeline_failed", syndication_id=syndication_id, error=str(e))
        nlp.mark_failed(user_id, item_id, str(e))
