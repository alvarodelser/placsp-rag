import httpx
import os
import tempfile
import urllib.parse
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from placsp.config import Config
from placsp.ai.embedder import Embedder
from placsp.parsers.pliego_html_parser import PliegoHTMLParser
import uuid
import json
import datetime

class PliegoPipeline:
    def __init__(self, cfg: Config, embedder: Embedder):
        self.cfg = cfg
        self.embedder = embedder
        self.ocr_url = cfg.ocr_url.rstrip('/')
        self.chunker_url = cfg.chunker_url.rstrip('/')
        self.client = httpx.Client(timeout=1200.0) # High timeout for OCR processing

    def download_pdf(self, url: str) -> Optional[str]:
        """Downloads a PDF from a given URL to a temporary file."""
        try:
            # We need to set a user agent as sometimes servers block default httpx/requests
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            # The URL might need properly encoded parameters
            # Wait, usually the raw URL is fine, but if it has encoded equals, let's just use it
            r = self.client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            
            # Check if it's actually a PDF
            content_type = r.headers.get('Content-Type', '')
            if 'pdf' not in content_type.lower() and b'%PDF' not in r.content[:5]:
                print(f"URL did not return a PDF: {url}")
                return None
                
            fd, path = tempfile.mkstemp(suffix='.pdf')
            with os.fdopen(fd, 'wb') as f:
                f.write(r.content)
            return path
        except Exception as e:
            print(f"Error downloading PDF from {url}: {e}")
            return None

    def run_ocr(self, pdf_path: str) -> Optional[str]:
        """Sends PDF to OCR service and returns parsed markdown."""
        try:
            with open(pdf_path, 'rb') as f:
                files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
                data = {'type_name': 'pdf'}
                r = self.client.post(f"{self.ocr_url}/services/ocr", data=data, files=files)
                r.raise_for_status()
                return r.json().get('content_parsed')
        except Exception as e:
            print(f"Error running OCR on {pdf_path}: {e}")
            return None

    def run_chunker(self, markdown_content: str) -> Optional[Dict[str, Any]]:
        """Sends markdown to chunking service and returns chunks."""
        try:
            # According to chunker main_API.py, it expects content_parsed as Form field
            data = {'content_parsed': markdown_content}
            r = self.client.post(f"{self.chunker_url}/services/chunking/doc", data=data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"Error running chunker: {e}")
            return None

    def chunk_text(self, text: str) -> list:
        """Sends text to chunker service and returns chunks with vectors."""
        try:
            r = self.client.post(
                f"{self.chunker_url}/chunk",
                json={"text": text}
            )
            r.raise_for_status()
            chunks = r.json().get('chunks', [])
            
            # Embed chunks
            if chunks:
                texts_to_embed = [c['text'] for c in chunks]
                vectors = self.embedder.embed(texts_to_embed)
                
                # Zip chunks with vectors
                return [
                    {
                        "chunk_index": i,
                        "chunk_title": c.get('title', ''),
                        "chunk_text": c['text'],
                        "vector": vectors[i] if i < len(vectors) else None
                    }
                    for i, c in enumerate(chunks)
                ]
            return []
        except Exception as e:
            print(f"Error chunking text: {e}")
            return []

    def process_tier1(self, record, link_url: str):
        """Processes Tier 1 (HTML criteria) for a single record and returns the Weaviate object."""
        try:
            r = self.client.get(link_url)
            r.raise_for_status()
            parser = PliegoHTMLParser(r.text)
            criteria = parser.parse()
            
            # Create Weaviate object for Placsp_pliego_criteria
            obj = {
                "class": "Placsp_pliego_criteria",
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"criteria_{record.syndication_id}")),
                "properties": {
                    "syndication_id": record.syndication_id,
                    "expediente": record.expediente or '',
                    "criteria_json": json.dumps(criteria.__dict__, ensure_ascii=False),
                    "source_url": link_url,
                    "extracted_at": datetime.datetime.utcnow().isoformat() + "Z"
                }
            }
            return obj
        except Exception as e:
            print(f"Error in process_tier1 for {record.syndication_id}: {e}")
            return None

    def process_pliego(self, pdf_url: str) -> Optional[List[Dict[str, Any]]]:
        """End-to-end processing of a single PDF URL -> Chunks with Embeddings."""
        print(f"Downloading {pdf_url}...")
        pdf_path = self.download_pdf(pdf_url)
        if not pdf_path:
            return None

        print(f"Running OCR on {pdf_path}...")
        markdown_text = self.run_ocr(pdf_path)
        
        # Cleanup temp file
        try:
            os.remove(pdf_path)
        except OSError:
            pass
            
        if not markdown_text:
            return None

        print("Chunking OCR text...")
        chunk_data = self.run_chunker(markdown_text)
        if not chunk_data or not chunk_data.get('chunk_list'):
            return None

        print(f"Embedding {len(chunk_data['chunk_list'])} chunks...")
        # Get embeddings for all chunks
        embeddings = self.embedder.embed(chunk_data['chunk_list'])
        
        processed_chunks = []
        for i, (text, emb) in enumerate(zip(chunk_data['chunk_list'], embeddings)):
            title = chunk_data.get('chunk_title', [])[i] if i < len(chunk_data.get('chunk_title', [])) else ""
            page = chunk_data.get('chunk_page_number', [])[i] if i < len(chunk_data.get('chunk_page_number', [])) else 0
            
            processed_chunks.append({
                'chunk_index': i,
                'chunk_text': text,
                'chunk_title': title,
                'page_number': page,
                'vector': emb
            })
            
        return processed_chunks
