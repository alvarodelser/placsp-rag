import httpx
import tempfile
import os
import json
import uuid
from typing import Dict, Any, List, Optional, Tuple
import structlog
from placsp.config import Config
from placsp.ai.extractor import PliegoExtractor
import sqlite3
from datetime import datetime, timezone

log = structlog.get_logger()

# Below this many characters of extracted text we assume the PDF is scanned
# (PyMuPDF returns ~nothing for image-only pages) and fall back to OCR.
_MIN_PYMUPDF_CHARS = 200
_CRITERIA_CLASS = "Placsp_pliego_criteria"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _criteria_uuid(syndication_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"criteria_{syndication_id}"))


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
        import fitz  # PyMuPDF — imported lazily so the module loads without it
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text() + "\n\n"
            return text
        except Exception as e:
            log.warning("pymupdf_extraction_failed", error=str(e))
            return ""

    def _run_ocr(self, pdf_path: str) -> str:
        """Fallback for scanned/image PDFs: send to the OCR service and return
        its plain-text (markdown) content."""
        try:
            with open(pdf_path, "rb") as f:
                files = {"file": (os.path.basename(pdf_path), f, "application/pdf")}
                r = self.client.post(
                    f"{self.cfg.ocr_url.rstrip('/')}/services/ocr",
                    data={"type_name": "pdf"}, files=files, timeout=600.0,
                )
                r.raise_for_status()
                return r.json().get("content_parsed") or ""
        except Exception as e:
            log.warning("ocr_fallback_failed", error=str(e))
            return ""

    def _get_pdf_text(self, url: str) -> str:
        """Download a pliego PDF and return its text, using PyMuPDF first and
        falling back to OCR when the PDF appears to be scanned/image-only."""
        path = self.download_pdf(url)
        if not path:
            return ""
        try:
            text = self.extract_text_from_pdf(path)
            if len(text.strip()) < _MIN_PYMUPDF_CHARS:
                log.info("pymupdf_thin_falling_back_to_ocr", url=url,
                         chars=len(text.strip()))
                ocr_text = self._run_ocr(path)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            return text
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

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
                continue  # skip this one but keep packing smaller high-score paragraphs
            extracted_text += p + "\n\n"

        return extracted_text

    _PCAP_KEYWORDS = ["penalidad", "penalización", "pago", "certificación",
                      "modificación", "subcontratación", "seguro", "cesión",
                      "resolución", "solvencia", "garantía"]
    _PPT_KEYWORDS = ["entregable", "fase", "sla", "nivel de servicio", "perfil",
                     "experiencia", "titulación", "certificación", "iso",
                     "tecnología", "software", "hardware", "lugar"]

    @staticmethod
    def _classify_pdf_links(pdf_links: List[dict]) -> Tuple[Optional[dict], Optional[dict]]:
        """Pick the PCAP (administrative) and PPT (technical) documents from the
        pliego links.  Handles combined documents (one PDF serving as both) and
        falls back to a generically-named 'pliego' for any unfilled slot.  Takes
        the first match per type rather than letting a later link overwrite it."""
        pcap = ppt = generic = None
        for link in pdf_links:
            name = link.get("nombre", "").lower()
            is_admin = "administrativ" in name or "pcap" in name
            is_tech = "técnic" in name or "tecnic" in name or "ppt" in name
            if is_admin and pcap is None:
                pcap = link
            if is_tech and ppt is None:
                ppt = link
            if not is_admin and not is_tech and "pliego" in name and generic is None:
                generic = link
        # A generically-named pliego backfills whichever specific slot is empty.
        if pcap is None:
            pcap = generic
        if ppt is None:
            ppt = generic
        return pcap, ppt

    def _extract_requirements(self, syndication_id: str, criteria: dict) -> Tuple[dict, dict]:
        """Return (pcap_json, ppt_json) for a licitación, reusing the shared
        Weaviate cache when present so extraction runs at most once per tender."""
        cached = self._get_cached_extraction(syndication_id)
        if cached is not None:
            log.info("extraction_cache_hit", syndication_id=syndication_id)
            return cached

        pcap_link, ppt_link = self._classify_pdf_links(criteria.get("pdf_links", []))
        pcap_json: dict = {}
        ppt_json: dict = {}

        if pcap_link:
            log.info("processing_pcap", url=pcap_link["url"])
            text = self._get_pdf_text(pcap_link["url"])
            if text:
                extracted = self._extractive_search(text, self._PCAP_KEYWORDS, max_chars=8000) or text[:8000]
                pcap_json = self.extractor.extract_from_pcap(extracted)

        if ppt_link and ppt_link is not pcap_link:
            log.info("processing_ppt", url=ppt_link["url"])
            text = self._get_pdf_text(ppt_link["url"])
            if text:
                extracted = self._extractive_search(text, self._PPT_KEYWORDS, max_chars=8000) or text[:8000]
                ppt_json = self.extractor.extract_from_ppt(extracted)

        self._save_extraction_cache(syndication_id, criteria, pcap_json, ppt_json)
        return pcap_json, ppt_json

    def run_pipeline(self, syndication_id: str, user_id: str, item_id: str, criteria: dict):
        """Per-licitación extraction (cached, shared) + per-user profile match."""
        log.info("nlp_pipeline_started", syndication_id=syndication_id, user_id=user_id)

        pcap_json, ppt_json = self._extract_requirements(syndication_id, criteria)

        profile = self._get_user_profile(user_id)
        match_result: dict = {}
        if profile:
            match_result = self.extractor.match_profile(profile, pcap_json, ppt_json, criteria)
        else:
            log.info("nlp_no_profile", user_id=user_id)

        self._save_analysis(user_id, item_id, pcap_json, ppt_json, match_result)
        log.info("nlp_pipeline_finished", syndication_id=syndication_id)

    # ── Per-licitación extraction cache (Weaviate) ──────────────────────────

    def _wv_headers(self) -> dict:
        key = self.cfg.weaviate_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _get_cached_extraction(self, syndication_id: str) -> Optional[Tuple[dict, dict]]:
        """Return cached (pcap_json, ppt_json) if a previous run stored them,
        else None.  Cache misses and errors are non-fatal — we just re-extract."""
        url = f"{self.cfg.weaviate_url.rstrip('/')}/v1/objects/{_CRITERIA_CLASS}/{_criteria_uuid(syndication_id)}"
        try:
            r = self.client.get(url, headers=self._wv_headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            props = r.json().get("properties", {})
            raw_pcap, raw_ppt = props.get("pcap_json"), props.get("ppt_json")
            if not raw_pcap and not raw_ppt:
                return None
            return json.loads(raw_pcap or "{}"), json.loads(raw_ppt or "{}")
        except Exception as e:
            log.warning("extraction_cache_read_failed", syndication_id=syndication_id, error=str(e))
            return None

    def _save_extraction_cache(self, syndication_id: str, criteria: dict,
                               pcap_json: dict, ppt_json: dict):
        """Persist the extraction on the shared criteria object (best-effort)."""
        base = self.cfg.weaviate_url.rstrip("/")
        obj_id = _criteria_uuid(syndication_id)
        props = {
            "pcap_json": json.dumps(pcap_json, ensure_ascii=False),
            "ppt_json": json.dumps(ppt_json, ensure_ascii=False),
            "pliegos_extracted_at": _now(),
        }
        try:
            # PATCH merges into the existing criteria object (created at ingestion).
            r = self.client.patch(
                f"{base}/v1/objects/{_CRITERIA_CLASS}/{obj_id}",
                json={"class": _CRITERIA_CLASS, "properties": props},
                headers=self._wv_headers(),
            )
            if r.status_code == 404:
                # No criteria object yet (ingestion hasn't seen it): create one.
                create_props = {"syndication_id": syndication_id,
                                "criteria_json": json.dumps(criteria, ensure_ascii=False),
                                "extracted_at": _now(), **props}
                r = self.client.post(
                    f"{base}/v1/objects",
                    json={"class": _CRITERIA_CLASS, "id": obj_id, "properties": create_props},
                    headers=self._wv_headers(),
                )
            r.raise_for_status()
        except Exception as e:
            log.warning("extraction_cache_write_failed", syndication_id=syndication_id, error=str(e))

    def _users_conn(self) -> sqlite3.Connection | None:
        """Connect to the shared users DB (owned by the search-api, mounted
        into this container).  Returns None — loudly — if it is missing."""
        db_path = os.getenv("USERS_DB", "/data/users.db")
        if not os.path.exists(db_path):
            log.error("users_db_missing", db_path=db_path,
                      hint="mount the placsp_feedback_data volume at /data")
            return None
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def _get_user_profile(self, user_id: str) -> dict:
        conn = self._users_conn()
        if conn is None:
            return {}
        try:
            row = conn.execute("SELECT profile_json FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            if row and row["profile_json"]:
                return json.loads(row["profile_json"])
        finally:
            conn.close()
        return {}

    def _save_analysis(self, user_id: str, item_id: str, pcap: dict, ppt: dict, match_result: dict):
        conn = self._users_conn()
        if conn is None:
            log.error("analysis_result_dropped", user_id=user_id, item_id=item_id)
            return
        try:
            conn.execute(
                "INSERT OR REPLACE INTO saved_items_analysis "
                "(user_id, item_id, pcap_json, ppt_json, veredicto, razonamiento, requisitos_evaluados, status, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'done', ?)",
                (user_id, item_id, json.dumps(pcap), json.dumps(ppt),
                 match_result.get("veredicto"), match_result.get("razonamiento_general"), json.dumps(match_result.get("requisitos_evaluados", [])), _now())
            )
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, user_id: str, item_id: str, reason: str = ""):
        """Record that the analysis failed so the UI can stop showing 'pending'."""
        conn = self._users_conn()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT INTO saved_items_analysis (user_id, item_id, razonamiento, status, analyzed_at) "
                "VALUES (?, ?, ?, 'failed', ?) "
                "ON CONFLICT(user_id, item_id) DO UPDATE SET "
                "status='failed', razonamiento=excluded.razonamiento, analyzed_at=excluded.analyzed_at",
                (user_id, item_id, reason[:500], _now())
            )
            conn.commit()
        finally:
            conn.close()
