import httpx
import tempfile
import os
import json
import fitz  # PyMuPDF
from typing import Dict, Any, List
import structlog
from placsp.config import Config
from placsp.ai.extractor import PliegoExtractor
import urllib.parse
import sqlite3
import re
from datetime import datetime

log = structlog.get_logger()

class NLPPipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = httpx.Client(timeout=120.0)
        self.extractor = PliegoExtractor(cfg)

    def download_pdf(self, url: str) -> str | None:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = self.client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', '')
            if 'pdf' not in content_type.lower() and b'%PDF' not in r.content[:5]:
                return None
            fd, path = tempfile.mkstemp(suffix='.pdf')
            with os.fdopen(fd, 'wb') as f:
                f.write(r.content)
            return path
        except Exception as e:
            log.warning("pdf_download_failed", url=url, error=str(e))
            return None

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Uses PyMuPDF to extract text fast."""
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text() + "\n\n"
            return text
        except Exception as e:
            log.warning("pymupdf_extraction_failed", error=str(e))
            return ""

    def _extractive_search(self, text: str, keywords: List[str], max_chars: int = 4000) -> str:
        """
        Extractive NLP Rule: Splits text into paragraphs and scores them based on 
        the presence of target keywords. Returns the most dense paragraphs up to max_chars.
        """
        paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
        
        scored_paragraphs = []
        for p in paragraphs:
            p_lower = p.lower()
            score = sum(p_lower.count(k.lower()) for k in keywords)
            if score > 0:
                scored_paragraphs.append((score, p))
                
        # Sort by score descending
        scored_paragraphs.sort(key=lambda x: x[0], reverse=True)
        
        extracted_text = ""
        for score, p in scored_paragraphs:
            if len(extracted_text) + len(p) > max_chars:
                break
            extracted_text += p + "\n\n"
            
        return extracted_text

    def run_pipeline(self, syndication_id: str, user_id: str, item_id: str, criteria: dict):
        """Runs the event-driven NLP pipeline."""
        log.info("nlp_pipeline_started", syndication_id=syndication_id, user_id=user_id)
        
        pdf_links = criteria.get('pdf_links', [])
        pcap_link = None
        ppt_link = None
        
        for link in pdf_links:
            name = link.get('nombre', '').lower()
            if 'administrativ' in name or 'pcap' in name:
                pcap_link = link
            elif 'técnic' in name or 'tecnic' in name or 'ppt' in name:
                ppt_link = link

        pcap_json = {}
        ppt_json = {}
        
        if pcap_link:
            log.info("processing_pcap", url=pcap_link['url'])
            path = self.download_pdf(pcap_link['url'])
            if path:
                text = self.extract_text_from_pdf(path)
                pcap_keywords = ["penalidad", "penalización", "pago", "certificación", "modificación", "subcontratación", "seguro", "cesión", "resolución", "solvencia", "garantía"]
                extracted_text = self._extractive_search(text, pcap_keywords, max_chars=8000)
                if not extracted_text:
                    extracted_text = text[:8000] # Fallback
                pcap_json = self.extractor.extract_from_pcap(extracted_text)
                os.remove(path)
                
        if ppt_link:
            log.info("processing_ppt", url=ppt_link['url'])
            path = self.download_pdf(ppt_link['url'])
            if path:
                text = self.extract_text_from_pdf(path)
                ppt_keywords = ["entregable", "fase", "sla", "nivel de servicio", "perfil", "experiencia", "titulación", "certificación", "iso", "tecnología", "software", "hardware", "lugar"]
                extracted_text = self._extractive_search(text, ppt_keywords, max_chars=8000)
                if not extracted_text:
                    extracted_text = text[:8000] # Fallback
                ppt_json = self.extractor.extract_from_ppt(extracted_text)
                os.remove(path)

        # Connect directly to the SQLite DB to fetch the user profile and save the analysis
        # In a real microservice architecture, we would call an API, but since we share the volume:
        profile = self._get_user_profile(user_id)
        
        match_result = {}
        if profile:
            # Run generative match
            match_result = self.extractor.match_profile(profile, pcap_json, ppt_json)

        # Save to DB
        self._save_analysis(user_id, item_id, pcap_json, ppt_json, match_result)
        log.info("nlp_pipeline_finished", syndication_id=syndication_id)

    def _get_user_profile(self, user_id: str) -> dict:
        db_path = os.getenv("USERS_DB", "/data/users.db")
        if not os.path.exists(db_path):
            return {}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT profile_json FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            if row and row["profile_json"]:
                return json.loads(row["profile_json"])
        finally:
            conn.close()
        return {}

    def _save_analysis(self, user_id: str, item_id: str, pcap: dict, ppt: dict, match_result: dict):
        db_path = os.getenv("USERS_DB", "/data/users.db")
        if not os.path.exists(db_path):
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO saved_items_analysis "
                "(user_id, item_id, pcap_json, ppt_json, veredicto, razonamiento, requisitos_evaluados, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, item_id, json.dumps(pcap), json.dumps(ppt),
                 match_result.get("veredicto"), match_result.get("razonamiento_general"), json.dumps(match_result.get("requisitos_evaluados", [])), datetime.utcnow().isoformat())
            )
            conn.commit()
        finally:
            conn.close()
