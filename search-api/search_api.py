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

import filters as filt

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
    q: str | None = Query(None),
    mode: str = Query("hybrid", pattern="^(hybrid|vector|keyword)$"),
    k: int = Query(15, ge=1, le=50),
    offset: int = Query(0, ge=0),
    alpha: float = Query(0.5, ge=0.0, le=1.0),
    sort: str | None = Query(None),
    cpv: list[str] | None = Query(None),
    nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None),
    procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None),
    pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None),
    deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None),
    budget_max: float | None = Query(None),
):
    where = filt.build_where(
        cpv=cpv, nuts=nuts, status=status, result=result,
        contract_type=contract_type, procedure=procedure,
        pub_from=pub_from, pub_to=pub_to,
        deadline_from=deadline_from, deadline_to=deadline_to,
        budget_min=budget_min, budget_max=budget_max,
    )
    query = (q or "").strip()

    # Guard: no query AND no filters -> don't dump the whole index.
    if not query and where is None:
        return {"query": None, "mode": "browse", "count": 0, "results": [], "errors": None}

    fields = "\n".join(FIELDS)
    args: list[str] = []
    try:
        if not query:  # browse mode
            mode = "browse"
            extra = "_additional { id }"
            args.append(filt.sort_to_gql(filt.build_sort(sort)))
        elif mode == "keyword":
            args.append(f"bm25: {{ query: {json.dumps(query)} }}")
            extra = "_additional { id score }"
        elif mode == "vector":
            args.append(f"nearVector: {{ vector: {json.dumps(_embed(query))} }}")
            extra = "_additional { id certainty }"
        else:  # hybrid
            args.append(f"hybrid: {{ query: {json.dumps(query)}, alpha: {alpha}, "
                        f"vector: {json.dumps(_embed(query))} }}")
            extra = "_additional { id score }"
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"vectorizer error: {exc}")

    if where is not None:
        args.append(filt.where_to_gql(where))
    args.append(f"limit: {k}")
    args.append(f"offset: {offset}")
    clause = ", ".join(args)

    gql = f"{{ Get {{ {CLASS}({clause}) {{ {fields} {extra} }} }} }}"
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
            "offset": offset, "results": results, "errors": data.get("errors")}
