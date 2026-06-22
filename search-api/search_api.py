"""PLACSP search backend (API only).

Embeds the query with the BGE-M3 vectorizer and runs a vector / hybrid / BM25 search over
the Placsp_licitaciones Weaviate class. The Weaviate API key stays server-side; the React
app (deployed separately) only calls /api/search. CORS is enabled for cross-origin use.

Env:
  VECTORIZER_URL    default http://localhost:8089
  WEAVIATE_URL      default http://localhost:8087
  WEAVIATE_API_KEY  (sent as Authorization: Bearer)
  PLACSP_CLASS      default Placsp_licitaciones
  CORS_ORIGINS      comma-separated allowed origins, default "*"
Run:  uvicorn search_api:app --host 0.0.0.0 --port 8092
"""
import json
import os

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

VECTORIZER_URL = os.getenv("VECTORIZER_URL", "http://localhost:8089").rstrip("/")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8087").rstrip("/")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY", "")
CLASS = os.getenv("PLACSP_CLASS", "Placsp_licitaciones")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

FIELDS = [
    "syndication_id", "title", "content", "category", "expediente",
    "contracting_authority", "org_top_level", "contract_type", "procedure",
    "status_label", "result_label", "budget_amount", "estimated_value",
    "awarded_amount", "cpv", "adjudicatario", "nuts_label", "city",
    "publication_date", "award_date", "funding_program", "source_url",
]

app = FastAPI(title="PLACSP Search API")
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"],
)


def _wv_headers():
    return {"Authorization": f"Bearer {WEAVIATE_API_KEY}"} if WEAVIATE_API_KEY else {}


def _embed(text: str) -> list[float]:
    r = httpx.post(f"{VECTORIZER_URL}/embed", json={"texts": [text], "normalize": True}, timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"][0]


@app.get("/api/health")
def health():
    return {"weaviate": WEAVIATE_URL, "vectorizer": VECTORIZER_URL, "class": CLASS}


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1),
    mode: str = Query("hybrid", pattern="^(hybrid|vector|keyword)$"),
    k: int = Query(15, ge=1, le=50),
    alpha: float = Query(0.5, ge=0.0, le=1.0),
):
    fields = "\n".join(FIELDS)
    try:
        if mode == "keyword":
            clause = f"bm25: {{ query: {json.dumps(q)} }}"
            extra = "_additional { id score }"
        elif mode == "vector":
            clause = f"nearVector: {{ vector: {json.dumps(_embed(q))} }}"
            extra = "_additional { id certainty }"
        else:  # hybrid
            clause = (f"hybrid: {{ query: {json.dumps(q)}, alpha: {alpha}, "
                      f"vector: {json.dumps(_embed(q))} }}")
            extra = "_additional { id score }"
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"vectorizer error: {exc}")

    gql = f"{{ Get {{ {CLASS}({clause}, limit: {k}) {{ {fields} {extra} }} }} }}"
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=120)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")

    data = r.json()
    hits = ((data.get("data") or {}).get("Get") or {}).get(CLASS) or []
    results = []
    for h in hits:
        add = h.pop("_additional", {}) or {}
        h["_id"] = add.get("id")
        h["_score"] = add.get("certainty", add.get("score"))
        results.append(h)
    return {"query": q, "mode": mode, "count": len(results),
            "results": results, "errors": data.get("errors")}
