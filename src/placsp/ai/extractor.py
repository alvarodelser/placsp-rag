import httpx
import json
from typing import Dict, Any, Optional
from placsp.config import Config
from placsp.ai.prompts.pliego import (
    PLIEGO_PCAP_EXTRACTION_PROMPT,
    PLIEGO_PPT_EXTRACTION_PROMPT,
    PLIEGO_MATCH_PROMPT,
)

class PliegoExtractor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base_url = cfg.ollama_url.rstrip('/')

    def _call_ollama(self, prompt: str) -> Optional[str]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.cfg.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=300.0 # High timeout for LLM
            )
            response.raise_for_status()
            return response.json().get('response', '')
        except Exception as e:
            print(f"Error calling Ollama: {e}")
            return None
    def _call_llm_json(self, prompt: str) -> dict:
        resp = self._call_ollama(prompt)
        if not resp: return {}
        # Clean markdown code blocks if the LLM adds them
        resp = resp.strip()
        if resp.startswith("```json"): resp = resp[7:]
        elif resp.startswith("```"): resp = resp[3:]
        if resp.endswith("```"): resp = resp[:-3]
        try:
            return json.loads(resp.strip())
        except Exception as e:
            print(f"JSON parsing error: {e}")
            return {}
    # --- Extraction Methods ---

    def extract_from_pcap(self, ocr_text: str) -> dict:
        # Limit text length to avoid context window issues
        prompt = PLIEGO_PCAP_EXTRACTION_PROMPT.format(ocr_text=ocr_text[:40000])
        return self._call_llm_json(prompt)

    def extract_from_ppt(self, ppt_text: str) -> dict:
        """Extracts technical requirements from the PPT."""
        prompt = PLIEGO_PPT_EXTRACTION_PROMPT.format(ppt_text=ppt_text[:40000])
        return self._call_llm_json(prompt)

    # --- Profile Match ---

    # The subset of parsed platform criteria that bears on whether a company
    # *may bid* — the reliable qualification gates fed into the match.
    _MATCH_CRITERIA_KEYS = (
        "clasificacion_empresarial", "condiciones_admision", "motivos_exclusion",
        "num_empleados_min", "garantia_definitiva_pct", "garantia_complementaria_pct",
        "criterios_adjudicacion",
    )

    def match_profile(self, profile: dict, pcap_json: dict, ppt_json: dict,
                      criteria: dict | None = None) -> dict:
        """Matches a user's profile against the extracted requirements plus the
        structured platform criteria (the most reliable qualification gates)."""
        criteria = criteria or {}
        gates = {k: criteria.get(k) for k in self._MATCH_CRITERIA_KEYS if criteria.get(k)}
        prompt = PLIEGO_MATCH_PROMPT.format(
            profile_json=json.dumps(profile, ensure_ascii=False),
            criteria_json=json.dumps(gates, ensure_ascii=False),
            pcap_json=json.dumps(pcap_json, ensure_ascii=False),
            ppt_json=json.dumps(ppt_json, ensure_ascii=False),
        )
        return self._call_llm_json(prompt)
