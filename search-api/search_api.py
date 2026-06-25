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
import subprocess

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import facets as fac
import feedback as fb
import filters as filt
from graph_api import router as graph_router

VECTORIZER_URL = os.getenv("VECTORIZER_URL", "http://localhost:8089").rstrip("/")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8087").rstrip("/")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY", "")
CLASS = os.getenv("PLACSP_CLASS", "Placsp_licitaciones")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]


def _resolve_version() -> str:
    """Backend version stamped onto feedback: APP_VERSION env, else the short
    git commit, else 'unknown'. Resolved once at import."""
    v = os.getenv("APP_VERSION")
    if v:
        return v
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__) or ".", stderr=subprocess.DEVNULL,
        )
        return out.decode().strip() or "unknown"
    except Exception:
        return "unknown"


APP_VERSION = _resolve_version()

FIELDS = [
    "syndication_id", "title", "content", "category", "expediente",
    "contracting_authority", "org_top_level", "contract_type", "procedure",
    "status_label", "result_label", "budget_amount", "estimated_value",
    "awarded_amount", "cpv", "adjudicatario", "nuts_label", "city",
    "publication_date", "award_date", "funding_program", "source_url",
]

app = FastAPI(title="PLACSP Search API")
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"],
)
app.include_router(graph_router)


def _fb_conn():
    return fb.connect(os.getenv("FEEDBACK_DB", "feedback.db"))


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
    # Aggregate cannot honor hybrid/vector ranking, so an exact match total is
    # only meaningful for browse/filter mode (no free-text query). With a query,
    # return total=None and let the client fall back to a page-size heuristic.
    total = None
    if not query:
        try:
            tg = fac.wrap_aggregate([fac.agg_total(CLASS, where)])
            tr = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": tg},
                            headers=_wv_headers(), timeout=120)
            tr.raise_for_status()
            total = fac.parse_aggregate(tr.json(), [], [])["total"]
        except httpx.HTTPError:
            total = None  # degrade: client uses the page-size heuristic
    return {"total": total, "offset": offset, "results": results, "errors": data.get("errors")}


@app.get("/api/weaviate/company/search")
def weaviate_company_search(
    q: str,
    k: int = Query(10, ge=1, le=50),
    alpha: float = Query(0.5, ge=0.0, le=1.0)
):
    """Semantic search against Placsp_companies to find a company by description."""
    query = q.strip()
    if not query:
        return {"results": []}
        
    try:
        vector = _embed(query)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"vectorizer error: {exc}")

    args = [
        f"hybrid: {{ query: {json.dumps(query)}, alpha: {alpha}, vector: {json.dumps(vector)} }}",
        f"limit: {k}"
    ]
    clause = ", ".join(args)
    fields = "nif name description _additional { id score }"
    
    gql = f"{{ Get {{ Placsp_companies({clause}) {{ {fields} }} }} }}"
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=120)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")

    data = r.json()
    if data.get("errors"):
        raise HTTPException(500, f"weaviate query errors: {data['errors']}")
        
    hits = ((data.get("data") or {}).get("Get") or {}).get("Placsp_companies") or []
    results = []
    for h in hits:
        add = h.pop("_additional", {}) or {}
        h["_id"] = add.get("id")
        h["_score"] = add.get("score")
        results.append(h)
        
    return {"query": q, "count": len(results), "results": results}


_FILTER_PARAMS = dict(
    cpv=None, nuts=None, status=None, result=None,
    contract_type=None, procedure=None,
    pub_from=None, pub_to=None,
    deadline_from=None, deadline_to=None,
    budget_min=None, budget_max=None,
)

def _filter_query_params():
    return dict(
        q=Query(None),
        cpv=Query(None), nuts=Query(None), status=Query(None), result=Query(None),
        contract_type=Query(None), procedure=Query(None),
        pub_from=Query(None), pub_to=Query(None),
        deadline_from=Query(None), deadline_to=Query(None),
        budget_min=Query(None, alias="budget_min"),
        budget_max=Query(None, alias="budget_max"),
    )


@app.get("/api/facets")
def facets(
    q: str | None = Query(None),
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
    """Fast facets: total count + group-by counts for all categorical dims.
    Budget/date histograms are served separately by /api/facets/distributions.
    """
    kwargs = dict(
        cpv=cpv, nuts=nuts, status=status, result=result,
        contract_type=contract_type, procedure=procedure,
        pub_from=pub_from, pub_to=pub_to,
        deadline_from=deadline_from, deadline_to=deadline_to,
        budget_min=budget_min, budget_max=budget_max,
    )
    where               = filt.build_where(**kwargs)
    where_cpv           = filt.build_where(**{**kwargs, "cpv": None})
    where_nuts          = filt.build_where(**{**kwargs, "nuts": None})
    where_status        = filt.build_where(**{**kwargs, "status": None})
    where_result        = filt.build_where(**{**kwargs, "result": None})
    where_contract_type = filt.build_where(**{**kwargs, "contract_type": None})
    where_procedure     = filt.build_where(**{**kwargs, "procedure": None})

    fields = [
        fac.agg_total(CLASS, where),
        fac.agg_total(CLASS, where_cpv,           alias="t_cpv"),
        fac.agg_total(CLASS, where_nuts,          alias="t_nuts"),
        fac.agg_total(CLASS, where_status,        alias="t_status"),
        fac.agg_total(CLASS, where_result,        alias="t_result"),
        fac.agg_total(CLASS, where_contract_type, alias="t_contract_type"),
        fac.agg_total(CLASS, where_procedure,     alias="t_procedure"),
        fac.agg_groupby_field(CLASS, where_nuts,           "nuts",               "nuts"),
        fac.agg_groupby_field(CLASS, where_status,         "status_code",        "status"),
        fac.agg_groupby_field(CLASS, where_result,         "result_code",        "result"),
        fac.agg_groupby_field(CLASS, where_contract_type,  "contract_type_code", "contract_type"),
        fac.agg_groupby_field(CLASS, where_procedure,      "procedure_code",     "procedure"),
    ]
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")

    return fac.parse_aggregate(r.json(), [], [], [],
                               extra_groupby=["status", "result", "contract_type", "procedure"])


@app.get("/api/facets/distributions")
def facets_distributions(
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
    """Budget histogram + date histograms via groupBy on pre-bucketed fields.
    3 Weaviate queries instead of 60+. Called lazily when the user opens the
    Budget or Dates tab in the filter panel.
    """
    kwargs = dict(
        cpv=cpv, nuts=nuts, status=status, result=result,
        contract_type=contract_type, procedure=procedure,
        pub_from=pub_from, pub_to=pub_to,
        deadline_from=deadline_from, deadline_to=deadline_to,
        budget_min=budget_min, budget_max=budget_max,
    )
    # Each dimension excludes its own filter so the user sees the full range.
    where_budget = filt.build_where(**{**kwargs, "budget_min": None, "budget_max": None})
    where_dates  = filt.build_where(**{**kwargs,
                                       "pub_from": None, "pub_to": None,
                                       "deadline_from": None, "deadline_to": None})

    budg_b = fac.budget_buckets()
    fields = [
        fac.agg_dist_groupby(CLASS, where_budget, "budget_bucket",   "budget"),
        fac.agg_dist_groupby(CLASS, where_dates,  "pub_month",       "pub_month"),
        fac.agg_dist_groupby(CLASS, where_dates,  "deadline_month",  "deadline_month"),
    ]
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")

    return fac.parse_distributions(r.json(), budg_b)


class ResultRef(BaseModel):
    id: str
    rank: int | None = None
    score: float | None = None


class FeedbackIn(BaseModel):
    search_id: str
    session_id: str
    query: str | None = None
    mode: str | None = None
    filters: dict = {}
    results: list[ResultRef] = []
    result_id: str


class FeedbackDel(BaseModel):
    search_id: str
    result_id: str


@app.post("/api/feedback")
def post_feedback(body: FeedbackIn):
    """Record a 'relevant' judgment. Lazily snapshots the search, derives the
    liked result's rank/score from that snapshot, and stamps the backend version."""
    conn = _fb_conn()
    try:
        fb.upsert_search(
            conn, search_id=body.search_id, session_id=body.session_id,
            query=body.query, mode=body.mode, filters=body.filters,
            results=[r.model_dump() for r in body.results], app_version=APP_VERSION,
        )
        match = next((r for r in body.results if r.id == body.result_id), None)
        fb.add_like(
            conn, search_id=body.search_id, session_id=body.session_id,
            result_id=body.result_id,
            result_rank=match.rank if match else None,
            result_score=match.score if match else None,
        )
    finally:
        conn.close()
    return {"ok": True, "app_version": APP_VERSION}


@app.delete("/api/feedback")
def delete_feedback(body: FeedbackDel):
    conn = _fb_conn()
    try:
        fb.remove_like(conn, search_id=body.search_id, result_id=body.result_id)
    finally:
        conn.close()
    return {"ok": True}
