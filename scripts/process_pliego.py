#!/usr/bin/env python3
import sys
import argparse
import httpx
import json
import uuid
import datetime
from typing import Dict, Any

sys.path.append('src')
from placsp.config import load_config
from placsp.ai.embedder import Embedder
from placsp.parsers.pliego_html_parser import PliegoHTMLParser
from placsp.ingestion.pliego_pipeline import PliegoPipeline
from placsp.ai.extractor import PliegoExtractor

def query_licitacion(cfg, syndication_id: str) -> Dict[str, Any]:
    query = """
    query {
      Get {
        Placsp_licitaciones(
          where: {
            path: ["syndication_id"]
            operator: Equal
            valueText: "%s"
          }
        ) {
          syndication_id
          expediente
          document_urls
        }
      }
    }
    """ % syndication_id
    
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql", json={'query': query}, headers=headers)
    r.raise_for_status()
    
    data = r.json().get('data', {}).get('Get', {}).get('Placsp_licitaciones', [])
    if not data:
        raise ValueError(f"No licitación found with syndication_id {syndication_id}")
    return data[0]

def upsert_criteria(cfg, lic: Dict[str, Any], criteria: Any, url: str):
    obj = {
        "class": "Placsp_pliego_criteria",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"criteria_{lic['syndication_id']}")),
        "properties": {
            "syndication_id": lic['syndication_id'],
            "expediente": lic.get('expediente', ''),
            "criteria_json": json.dumps(criteria.__dict__, ensure_ascii=False),
            "source_url": url,
            "extracted_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
    }
    
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/objects", json=obj, headers=headers)
    
    if r.status_code == 422: # Already exists, try to update
        r = httpx.put(f"{cfg.weaviate_url.rstrip('/')}/v1/objects/{obj['class']}/{obj['id']}", json=obj, headers=headers)
    r.raise_for_status()
    print("Successfully saved criteria to Weaviate.")

def upsert_chunks(cfg, lic: Dict[str, Any], chunks: list, pdf_url: str, pliego_type: str):
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    
    objects = []
    for chunk in chunks:
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chunk_{lic['syndication_id']}_{pliego_type}_{chunk['chunk_index']}"))
        obj = {
            "class": "Placsp_pliego_chunks",
            "id": chunk_id,
            "properties": {
                "syndication_id": lic['syndication_id'],
                "expediente": lic.get('expediente', ''),
                "pliego_type": pliego_type,
                "chunk_index": chunk['chunk_index'],
                "chunk_title": chunk.get('chunk_title', ''),
                "chunk_text": chunk['chunk_text'],
                "source_pdf_url": pdf_url
            },
            "vector": chunk['vector']
        }
        objects.append(obj)
        
    # Batch insert
    batch_payload = {"objects": objects}
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/batch/objects", json=batch_payload, headers=headers)
    r.raise_for_status()
    print(f"Successfully saved {len(chunks)} chunks to Weaviate.")


def main():
    parser = argparse.ArgumentParser(description="Process Pliegos for a given licitación")
    parser.add_argument("--syndication-id", required=True, help="The syndication_id of the licitación")
    parser.add_argument("--tier", type=int, choices=[1, 2], default=1, help="Processing tier (1: HTML parse only, 2: HTML + PCAP OCR)")
    args = parser.parse_args()

    cfg = load_config()
    embedder = Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout)
    extractor = PliegoExtractor(cfg)
    pipeline = PliegoPipeline(cfg, embedder)
    
    print(f"Looking up licitación {args.syndication_id}...")
    try:
        lic = query_licitacion(cfg, args.syndication_id)
    except Exception as e:
        print(e)
        return

    doc_urls = lic.get('document_urls', [])
    index_url = None
    for url in doc_urls:
        if 'GetDocumentByIdServlet' in url:
            index_url = url
            break
            
    if not index_url:
        print("No pliego index URL found in document_urls.")
        # Fallback to the known pattern if the user passed something we can guess
        return
        
    print(f"Fetching Pliego HTML from {index_url}...")
    try:
        r = httpx.get(index_url, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        html_content = r.text
    except Exception as e:
        print(f"Failed to fetch HTML: {e}")
        return
        
    print("Running Tier 1: Parsing HTML...")
    parser = PliegoHTMLParser(html_content)
    criteria = parser.parse()
    
    print("\n--- Extracted Criteria (Tier 1) ---")
    print(json.dumps(criteria.__dict__, indent=2, ensure_ascii=False))
    
    print("\nSaving criteria to Weaviate...")
    upsert_criteria(cfg, lic, criteria, index_url)
    
    if args.tier == 2:
        print("\n=== Running Tier 2: PCAP OCR ===")
        # Find the PCAP link
        pcap_link = None
        for link in criteria.pdf_links:
            name = link.get('nombre', '').lower()
            if 'administrativ' in name or 'pcap' in name:
                pcap_link = link
                break
                
        if not pcap_link:
            print("Could not identify the PCAP document in the PDF links. Skipping Tier 2.")
            return
            
        print(f"Identified PCAP document: {pcap_link['nombre']}")
        chunks = pipeline.process_pliego(pcap_link['url'])
        if chunks:
            print(f"Generated {len(chunks)} embedded chunks from OCR text.")
            upsert_chunks(cfg, lic, chunks, pcap_link['url'], "administrativo")
            
            # Combine full text for LLM
            full_text = "\n\n".join([c['chunk_text'] for c in chunks])
            print("Sending text to Ollama for structured extraction...")
            pcap_json = extractor.extract_from_pcap(full_text)
            print("\n--- Extracted PCAP Terms (Ollama) ---")
            print(pcap_json)
            
            print("\n--- Running AI Analytics ---")
            
            print("1. Scoring Strategy...")
            strategy_json = extractor.analyze_scoring_strategy(criteria.__dict__)
            print(strategy_json)
            
            if pcap_json:
                print("\n2. Risk Analysis...")
                risk_json = extractor.analyze_risks(pcap_json, criteria.__dict__)
                print(risk_json)
                
                print("\n3. Executive Summary (Bid/No-Bid)...")
                exec_summary = extractor.generate_executive_summary(criteria.__dict__, pcap_json)
                print(exec_summary)

        else:
            print("Failed to process PCAP PDF.")

if __name__ == "__main__":
    main()
