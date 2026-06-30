import httpx
import json
from typing import Dict, Any, Optional
from .config import Config

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

    def summarize_html_criteria(self, criteria_dict: dict) -> Optional[str]:
        prompt = f"""
        Convierte la siguiente información estructurada extraída de un pliego de licitación
        en un resumen claro y conciso en español, enfocado en lo que una empresa 
        necesitaría saber rápidamente para decidir si presentarse. 
        Formatea la salida en JSON con las claves: "resumen_general", "puntos_clave", "requisitos_criticos".
        
        Datos:
        {json.dumps(criteria_dict, ensure_ascii=False, indent=2)}
        """
        return self._call_ollama(prompt)

    def extract_from_pcap(self, ocr_text: str) -> Optional[str]:
        prompt = f"""
        Del siguiente texto del Pliego de Cláusulas Administrativas Particulares (PCAP), 
        extrae en formato JSON la siguiente información:
        - penalidades: Lista de diccionarios con {{tipo, importe_o_porcentaje, descripcion}}
        - forma_pago: Diccionario con {{plazo_dias, certificaciones}}
        - modificaciones_contrato: Diccionario con {{permitidas (booleano), limite_porcentaje, condiciones}}
        - subcontratacion: Diccionario con {{permitida (booleano), limite_porcentaje, condiciones}}
        - seguros: Lista de diccionarios con {{tipo, importe_minimo}}
        - cesion: Diccionario con {{permitida (booleano), condiciones}}
        - resolucion: Diccionario con {{causas (lista), procedimiento}}

        Si alguna información no se encuentra, omite la clave o usa null.
        Asegúrate de que la salida sea JSON válido.

        Texto del PCAP:
        {ocr_text[:40000]} # Limit text length to avoid context window issues
        """
        return self._call_ollama(prompt)
