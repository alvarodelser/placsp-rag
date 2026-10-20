"""HTTP clients for the services already deployed on the server.

- nlp_service: POST /nli, /summarize, /ner, /resolve (the same modules its relation pipeline uses)
- vectorizer (BGE-M3): POST /embed
OCR is called from textract.py. Every call is logged to service_call with its duration and
input/output sizes, which is what the report aggregates.
"""
import json
import time

import httpx

from placsp_pilot.config import PilotConfig
from placsp_pilot.store import Store


class ServiceError(RuntimeError):
    pass


class Services:
    def __init__(self, cfg: PilotConfig, store: Store, need_nlp: bool = True):
        if need_nlp and not cfg.nlp_url:
            raise SystemExit("NLP_SERVICE_URL is not set: point it at the server's nlp_service (e.g. http://nlp-service:8000)")
        self.cfg = cfg
        self.store = store
        self.client = httpx.Client(timeout=cfg.service_timeout)

    def _post(self, service: str, url: str, body: dict, *, task: str, exp_id=None, sha=None,
              input_chars: int = 0, retries: int = 2) -> dict:
        last, detail = None, ""
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                r = self.client.post(url, json=body)
                r.raise_for_status()
                out = r.json()
                self.store.log_call(service=service, task=task, exp_id=exp_id, sha=sha, input_chars=input_chars,
                                    output_chars=len(r.content), wall_ms=int((time.time() - t0) * 1000), ok=1)
                return out
            except (httpx.HTTPError, ValueError) as e:
                last = e
                detail = getattr(getattr(e, "response", None), "text", "") or ""
                self.store.log_call(service=service, task=task, exp_id=exp_id, sha=sha, input_chars=input_chars,
                                    wall_ms=int((time.time() - t0) * 1000), ok=0,
                                    error=f"{type(e).__name__}: {e} {detail[:200]}"[:500])
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status is not None and status < 500:
                    break  # a 4xx will not get better on retry
                time.sleep(2 ** attempt)
        # The service's own body says why (e.g. its model backend is down); httpx's message does not.
        raise ServiceError(f"{last} {detail[:300]}".strip())

    def summarize(self, profile: str, fields: dict, **kw) -> dict:
        size = sum(len(json.dumps(v, ensure_ascii=False)) for v in fields.values())
        out = self._post("nlp", f"{self.cfg.nlp_url}/summarize", {"profile": profile, "fields": fields},
                         task=f"summarize:{profile}", input_chars=size, **kw)
        return out["result"]

    def nli(self, text: str, hypotheses: list[str], template: str = "{}", **kw) -> list[dict]:
        out = self._post("nlp", f"{self.cfg.nlp_url}/nli",
                         {"text": text, "hypotheses": hypotheses, "hypothesis_template": template},
                         task="nli", input_chars=len(text), **kw)
        return out["scores"]

    def ner(self, text: str, schema: dict, **kw) -> dict:
        return self._post("nlp", f"{self.cfg.nlp_url}/ner", {"text": text, "schema": schema},
                          task="ner", input_chars=len(text), **kw)

    def resolve(self, entities: list[dict], relations: list[dict], **kw) -> dict:
        size = sum(len(e.get("evidence", "")) for e in entities)
        return self._post("nlp", f"{self.cfg.nlp_url}/resolve", {"entities": entities, "relations": relations},
                          task="resolve", input_chars=size, **kw)

    def coref_links(self, text: str, candidates: list[dict], context: str | None = None, **kw) -> list[dict]:
        out = self._post("nlp", f"{self.cfg.nlp_url}/coref/links", {"text": text, "candidates": candidates, "context": context},
                         task="coref", input_chars=len(text), **kw)
        return out["links"]

    def embed(self, texts: list[str], **kw) -> list[list[float]]:
        out = self._post("vectorizer", f"{self.cfg.vectorizer_url}/embed", {"texts": texts, "normalize": True},
                         task="embed", input_chars=sum(map(len, texts)), **kw)
        return out["embeddings"]
