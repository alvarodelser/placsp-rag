import httpx
import json
from typing import Dict, Any, Optional
from placsp.config import Config
from placsp.ai.prompts.pliego import PLIEGO_HTML_SUMMARY_PROMPT, PLIEGO_PCAP_EXTRACTION_PROMPT
from placsp.ai.prompts.analysis import RISK_ANALYSIS_PROMPT, SCORING_STRATEGY_PROMPT, EXECUTIVE_SUMMARY_PROMPT

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

    # --- Base Extraction Methods ---

    def summarize_html_criteria(self, criteria_dict: dict) -> Optional[str]:
        criteria_str = json.dumps(criteria_dict, ensure_ascii=False, indent=2)
        prompt = PLIEGO_HTML_SUMMARY_PROMPT.format(criteria_json=criteria_str)
        return self._call_ollama(prompt)

    def extract_from_pcap(self, ocr_text: str) -> Optional[str]:
        # Limit text length to avoid context window issues
        prompt = PLIEGO_PCAP_EXTRACTION_PROMPT.format(ocr_text=ocr_text[:40000])
        return self._call_ollama(prompt)

    # --- Analytical Curation Methods ---

    def analyze_risks(self, pcap_json: str, criteria_dict: dict) -> Optional[str]:
        criteria_str = json.dumps(criteria_dict, ensure_ascii=False, indent=2)
        prompt = RISK_ANALYSIS_PROMPT.format(pcap_json=pcap_json, criteria_json=criteria_str)
        return self._call_ollama(prompt)

    def extract_from_ppt(self, ppt_text: str) -> dict:
        """Extracts technical requirements from PPT using Gemma."""
        from placsp.ai.prompts.pliego import PLIEGO_PPT_EXTRACTION_PROMPT
        prompt = PLIEGO_PPT_EXTRACTION_PROMPT.format(ppt_text=ppt_text)
        return self._call_llm_json(prompt)

    def match_profile(self, profile: dict, pcap_json: dict, ppt_json: dict) -> dict:
        """Matches a user's profile against the extracted requirements."""
        from placsp.ai.prompts.pliego import PLIEGO_MATCH_PROMPT
        prompt = PLIEGO_MATCH_PROMPT.format(
            profile_json=json.dumps(profile, ensure_ascii=False),
            pcap_json=json.dumps(pcap_json, ensure_ascii=False),
            ppt_json=json.dumps(ppt_json, ensure_ascii=False)
        )
        return self._call_llm_json(prompt)

    def analyze_scoring_strategy(self, criteria_dict: dict) -> Optional[str]:
        criteria_str = json.dumps(criteria_dict, ensure_ascii=False, indent=2)
        prompt = SCORING_STRATEGY_PROMPT.format(criteria_json=criteria_str)
        return self._call_ollama(prompt)

    def generate_executive_summary(self, criteria_dict: dict, pcap_json: str) -> Optional[str]:
        criteria_str = json.dumps(criteria_dict, ensure_ascii=False, indent=2)
        prompt = EXECUTIVE_SUMMARY_PROMPT.format(criteria_json=criteria_str, pcap_json=pcap_json)
        return self._call_ollama(prompt)
