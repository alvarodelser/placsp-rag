from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import httpx
import uuid
import json
import datetime
from typing import Dict, Any

from placsp.config import load_config
from placsp.ai.embedder import Embedder
from placsp.ingestion.pliego_pipeline import PliegoPipeline
from placsp.ai.extractor import PliegoExtractor
from placsp.parsers.pliego_html_parser import PliegoHTMLParser
import structlog

log = structlog.get_logger()
app = FastAPI(title="Placsp Ingester API")

# Load configuration and initialize components
cfg = load_config()
embedder = Embedder(cfg)
pipeline = PliegoPipeline(cfg, embedder)
extractor = PliegoExtractor(cfg)

def _get_licitacion(syndication_id: str) -> Dict[str, Any]:
    """Fetch the licitacion object from Weaviate."""
    where = f'{{ path: ["syndication_id"], operator: Equal, valueText: "{syndication_id}" }}'
    gql = f"{{ Get {{ Placsp_licitaciones(where: {where}) {{ syndication_id expediente source_url }} }} }}"
    
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql", json={"query": gql}, headers=headers)
    r.raise_for_status()
    
    data = r.json().get('data', {}).get('Get', {}).get('Placsp_licitaciones', [])
    if not data:
        raise ValueError(f"No licitación found with syndication_id {syndication_id}")
    return data[0]

def _upsert_weaviate_obj(obj: Dict[str, Any]):
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/objects", json=obj, headers=headers)
    if r.status_code == 422: # Already exists, try to update
        r = httpx.put(f"{cfg.weaviate_url.rstrip('/')}/v1/objects/{obj['class']}/{obj['id']}", json=obj, headers=headers)
    r.raise_for_status()

def run_tier2_analysis(syndication_id: str):
    """Background task to run full Tier 2 analysis."""
    log.info("tier2_start", syndication_id=syndication_id)
    try:
        lic = _get_licitacion(syndication_id)
        source_url = lic.get('source_url')
        if not source_url or "contrataciondelestado.es/wps/portal" not in source_url:
            log.warning("tier2_skipped_no_url", syndication_id=syndication_id)
            return

        # Fetch index HTML
        r = httpx.get(source_url)
        r.raise_for_status()
        
        parser = PliegoHTMLParser(r.text)
        criteria = parser.parse()
        
        # Save Tier 1 just in case it wasn't saved
        obj = {
            "class": "Placsp_pliego_criteria",
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"criteria_{lic['syndication_id']}")),
            "properties": {
                "syndication_id": lic['syndication_id'],
                "expediente": lic.get('expediente', ''),
                "criteria_json": json.dumps(criteria.__dict__, ensure_ascii=False),
                "source_url": source_url,
                "extracted_at": datetime.datetime.utcnow().isoformat() + "Z"
            }
        }
        _upsert_weaviate_obj(obj)
        
        # Identify PCAP link
        pcap_link = None
        for link in criteria.pdf_links:
            name = link.get('nombre', '').lower()
            if 'administrativ' in name or 'pcap' in name:
                pcap_link = link
                break
                
        if not pcap_link:
            log.info("tier2_no_pcap", syndication_id=syndication_id)
            return
            
        # Run OCR + Chunker
        chunks = pipeline.process_pliego(pcap_link['url'])
        if chunks:
            # Upsert Chunks
            for chunk in chunks:
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chunk_{lic['syndication_id']}_administrativo_{chunk['chunk_index']}"))
                chunk_obj = {
                    "class": "Placsp_pliego_chunks",
                    "id": chunk_id,
                    "properties": {
                        "syndication_id": lic['syndication_id'],
                        "expediente": lic.get('expediente', ''),
                        "pliego_type": "administrativo",
                        "chunk_index": chunk['chunk_index'],
                        "chunk_title": chunk.get('chunk_title', ''),
                        "chunk_text": chunk['chunk_text'],
                        "source_pdf_url": pcap_link['url']
                    },
                    "vector": chunk['vector']
                }
                _upsert_weaviate_obj(chunk_obj)
            
            # Combine full text for LLM
            full_text = "\n\n".join([c['chunk_text'] for c in chunks])
            
            pcap_json = extractor.extract_from_pcap(full_text)
            strategy_json = extractor.analyze_scoring_strategy(criteria.__dict__)
            risk_json = extractor.analyze_risks(pcap_json, criteria.__dict__) if pcap_json else None
            exec_summary = extractor.generate_executive_summary(criteria.__dict__, pcap_json) if pcap_json else None
            
            # Save the analytical results back into the Pliego_criteria object
            obj["properties"]["pcap_analysis_json"] = pcap_json
            obj["properties"]["scoring_strategy_json"] = strategy_json
            obj["properties"]["risk_analysis_json"] = risk_json
            obj["properties"]["executive_summary_json"] = exec_summary
            
            _upsert_weaviate_obj(obj)
            log.info("tier2_success", syndication_id=syndication_id)
            
    except Exception as e:
        log.error("tier2_failed", syndication_id=syndication_id, error=str(e))

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
    try:
        from placsp.ai.nlp_pipeline import NLPPipeline
        from placsp.ai.parser import PliegoHTMLParser
        
        # 1. Fetch licitacion metadata to get the source URL
        lic = _get_licitacion(syndication_id)
        source_url = lic.get('source_url')
        if not source_url or "contrataciondelestado.es" not in source_url:
            log.warning("nlp_skipped_no_url", syndication_id=syndication_id)
            return
            
        # 2. Fetch and parse criteria from the source HTML
        r = httpx.get(source_url)
        r.raise_for_status()
        parser = PliegoHTMLParser(r.text)
        criteria = parser.parse()
        
        # 3. Run Pipeline
        pipeline = NLPPipeline(cfg)
        pipeline.run_pipeline(syndication_id, user_id, item_id, criteria.__dict__)
    except Exception as e:
        log.error("nlp_pipeline_failed", syndication_id=syndication_id, error=str(e))
