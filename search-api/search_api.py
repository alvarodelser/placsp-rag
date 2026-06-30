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
import sqlite3
import subprocess

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

import auth
import facets as fac
import feedback as fb
import filters as filt
import users
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"],
)
app.include_router(graph_router)


def _fb_conn():
    return fb.connect(os.getenv("FEEDBACK_DB", "feedback.db"))


def _users_conn():
    return users.connect(os.getenv("USERS_DB", "users.db"))


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
    ]
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")

    return fac.parse_aggregate(r.json(), [], [], [])


def _common_kwargs(cpv, nuts, status, result, contract_type, procedure,
                   pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max):
    return dict(cpv=cpv, nuts=nuts, status=status, result=result,
                contract_type=contract_type, procedure=procedure,
                pub_from=pub_from, pub_to=pub_to,
                deadline_from=deadline_from, deadline_to=deadline_to,
                budget_min=budget_min, budget_max=budget_max)


def _run_groupby(where, wv_prop: str, alias: str) -> dict:
    """Execute a single groupBy aggregate and return {value: count}."""
    gql = fac.wrap_aggregate([fac.agg_groupby_field(CLASS, where, wv_prop, alias)])
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")
    return fac.parse_groupby(r.json(), alias)


@app.get("/api/facets/budget")
def facets_budget(
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
    """Budget histogram — 1 groupBy query. Excludes budget filter so the full range is visible."""
    kwargs = _common_kwargs(cpv, nuts, status, result, contract_type, procedure,
                            pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max)
    where = filt.build_where(**{**kwargs, "budget_min": None, "budget_max": None})
    budg_b = fac.budget_buckets()
    gql = fac.wrap_aggregate([fac.agg_dist_groupby(CLASS, where, "budget_bucket", "budget")])
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")
    return fac.parse_distributions(r.json(), budg_b)


@app.get("/api/facets/dates")
def facets_dates(
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
    """Date histograms — 2 groupBy queries. Excludes date filters so the full timeline is visible."""
    kwargs = _common_kwargs(cpv, nuts, status, result, contract_type, procedure,
                            pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max)
    where = filt.build_where(**{**kwargs,
                                "pub_from": None, "pub_to": None,
                                "deadline_from": None, "deadline_to": None})
    budg_b = fac.budget_buckets()
    fields = [
        fac.agg_dist_groupby(CLASS, where, "pub_month",      "pub_month"),
        fac.agg_dist_groupby(CLASS, where, "deadline_month", "deadline_month"),
    ]
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")
    return fac.parse_distributions(r.json(), budg_b)


def _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                  pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                  exclude: str, wv_prop: str, alias: str):
    kwargs = _common_kwargs(cpv, nuts, status, result, contract_type, procedure,
                            pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max)
    where = filt.build_where(**{**kwargs, exclude: None})
    return _run_groupby(where, wv_prop, alias)


def _cat_params():
    """Shared Query params for all per-tab categorical endpoints."""
    return (Query(None), Query(None), Query(None), Query(None), Query(None), Query(None),
            Query(None), Query(None), Query(None), Query(None), Query(None), Query(None))


@app.get("/api/facets/location")
def facets_location(
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    return _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                         pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                         exclude="nuts", wv_prop="nuts", alias="nuts")


@app.get("/api/facets/status")
def facets_status(
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    return _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                         pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                         exclude="status", wv_prop="status_code", alias="status")


@app.get("/api/facets/result")
def facets_result(
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    return _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                         pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                         exclude="result", wv_prop="result_code", alias="result")


@app.get("/api/facets/type")
def facets_type(
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    return _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                         pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                         exclude="contract_type", wv_prop="contract_type_code", alias="contract_type")


@app.get("/api/facets/procedure")
def facets_procedure(
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    return _cat_endpoint(cpv, nuts, status, result, contract_type, procedure,
                         pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max,
                         exclude="procedure", wv_prop="procedure_code", alias="procedure")


@app.get("/api/facets/cpv")
def facets_cpv(
    codes: list[str] | None = Query(None),   # CPV codes visible in current miller column
    cpv: list[str] | None = Query(None), nuts: list[str] | None = Query(None),
    status: list[str] | None = Query(None), result: list[str] | None = Query(None),
    contract_type: list[str] | None = Query(None), procedure: list[str] | None = Query(None),
    pub_from: str | None = Query(None), pub_to: str | None = Query(None),
    deadline_from: str | None = Query(None), deadline_to: str | None = Query(None),
    budget_min: float | None = Query(None), budget_max: float | None = Query(None),
):
    """Count documents per CPV node for the visible miller column.
    `codes` = the CPV codes currently shown in the active column (max ~50).
    Runs one alias per code (prefix-match), all in a single GraphQL request.
    """
    visible = (codes or [])[:50]
    if not visible:
        return {}
    kwargs = _common_kwargs(cpv, nuts, status, result, contract_type, procedure,
                            pub_from, pub_to, deadline_from, deadline_to, budget_min, budget_max)
    base_where = filt.build_where(**{**kwargs, "cpv": None})
    fields = []
    for i, code in enumerate(visible):
        code_where = filt.cpv_code_where(code)
        combined   = ({"operator": "And", "operands": [base_where, code_where]}
                      if base_where else code_where)
        fields.append(fac.agg_total(CLASS, combined, alias=f"c{i}"))
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")
    agg = ((r.json().get("data") or {}).get("Aggregate") or {})
    return {
        code: ((agg.get(f"c{i}") or [{}])[0].get("meta") or {}).get("count", 0)
        for i, code in enumerate(visible)
    }


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


# ── Auth endpoints ──────────────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: str
    password: str
    display_name: str


@app.post("/auth/register")
def register(body: RegisterIn):
    """Create a new user account, set auth cookies, return the user."""
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not body.display_name.strip():
        raise HTTPException(400, "Display name is required")

    conn = _users_conn()
    try:
        hashed = auth.hash_password(body.password)
        try:
            user = users.create_user(
                conn, email=email, display_name=body.display_name,
                hashed_password=hashed,
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Email already registered")

        access = auth.create_access_token(user["user_id"], user["email"])
        raw_refresh, refresh_hash = auth.create_refresh_token()
        users.store_refresh_token(
            conn, user_id=user["user_id"],
            token_hash=refresh_hash, expires_at=auth.refresh_token_expiry(),
        )
        users.log_event(conn, user_id=user["user_id"], event_type="register")
    finally:
        conn.close()

    resp = JSONResponse({
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
    })
    auth.set_auth_cookies(resp, access, raw_refresh)
    return resp


@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    """Authenticate with email (username field) + password.  Sets auth cookies."""
    conn = _users_conn()
    try:
        user = users.get_user_by_email(conn, form.username)
        if not user or not auth.verify_password(form.password, user["hashed_password"]):
            raise HTTPException(401, "Invalid email or password")
        if not user.get("is_active", True):
            raise HTTPException(403, "Account disabled")

        users.update_last_seen(conn, user["user_id"])
        access = auth.create_access_token(user["user_id"], user["email"])
        raw_refresh, refresh_hash = auth.create_refresh_token()
        users.store_refresh_token(
            conn, user_id=user["user_id"],
            token_hash=refresh_hash, expires_at=auth.refresh_token_expiry(),
        )
        users.log_event(conn, user_id=user["user_id"], event_type="login")
    finally:
        conn.close()

    resp = JSONResponse({
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
    })
    auth.set_auth_cookies(resp, access, raw_refresh)
    return resp


@app.post("/auth/refresh")
def refresh(request: Request):
    """Issue a fresh access token using the refresh-token cookie."""
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh:
        raise HTTPException(401, "No refresh token")

    # We need the user_id from the (possibly expired) access token.
    access_tok = request.cookies.get("access_token", "")
    try:
        import jwt as _jwt
        payload = _jwt.decode(access_tok, auth.SECRET_KEY,
                              algorithms=[auth.ALGORITHM],
                              options={"verify_exp": False})
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(401, "Cannot identify user from access token")

    conn = _users_conn()
    try:
        token_hash = auth.hash_refresh_token(raw_refresh)
        if not users.validate_refresh_token(conn, user_id=user_id,
                                            token_hash=token_hash):
            raise HTTPException(401, "Refresh token invalid or expired")

        user = users.get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(401, "User not found")

        users.update_last_seen(conn, user_id)
    finally:
        conn.close()

    new_access = auth.create_access_token(user["user_id"], user["email"])
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        key="access_token", value=new_access, httponly=True,
        secure=auth._SECURE, samesite="lax",
        max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60, path="/",
    )
    return resp


@app.post("/auth/logout")
def logout(request: Request):
    """Clear auth cookies and invalidate all refresh tokens."""
    user_id = None
    access_tok = request.cookies.get("access_token", "")
    try:
        payload = auth.decode_access_token(access_tok)
        user_id = payload["sub"]
    except Exception:
        pass  # best-effort: clear cookies even if token is invalid/expired

    if user_id:
        conn = _users_conn()
        try:
            users.delete_user_refresh_tokens(conn, user_id)
            users.log_event(conn, user_id=user_id, event_type="logout")
        finally:
            conn.close()

    resp = JSONResponse({"ok": True})
    auth.clear_auth_cookies(resp)
    return resp


@app.get("/auth/me")
def me(current: dict = Depends(auth.get_current_user)):
    """Return the authenticated user's profile."""
    conn = _users_conn()
    try:
        user = users.get_user_by_id(conn, current["user_id"])
        if not user:
            raise HTTPException(404, "User not found")
        users.update_last_seen(conn, current["user_id"])
    finally:
        conn.close()
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
    }


# ── User-space endpoints (protected) ───────────────────────────────────────

class SaveItemIn(BaseModel):
    item_id: str
    syndication_id: str | None = None
    title: str | None = None


@app.get("/api/users/me/saved")
def list_user_saved(
    current: dict = Depends(auth.get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List the current user's saved licitaciones."""
    conn = _users_conn()
    try:
        items = users.list_saved(conn, current["user_id"],
                                 offset=offset, limit=limit)
        total = users.count_saved(conn, current["user_id"])
    finally:
        conn.close()
    return {"total": total, "offset": offset, "items": items}


@app.get("/api/users/me/saved/ids")
def get_user_saved_ids(current: dict = Depends(auth.get_current_user)):
    """Return just the item IDs for fast UI hydration."""
    conn = _users_conn()
    try:
        ids = users.get_saved_ids(conn, current["user_id"])
    finally:
        conn.close()
    return {"ids": ids}


@app.post("/api/users/me/saved")
def save_user_item(body: SaveItemIn,
                   current: dict = Depends(auth.get_current_user)):
    """Save a licitación to the current user's space."""
    conn = _users_conn()
    try:
        item = users.save_item(
            conn, user_id=current["user_id"], item_id=body.item_id,
            syndication_id=body.syndication_id, title=body.title,
        )
        users.log_event(
            conn, user_id=current["user_id"],
            event_type="save", item_id=body.item_id,
        )
    finally:
        conn.close()
    return {"ok": True, "item": item}


@app.delete("/api/users/me/saved/{item_id}")
def unsave_user_item(item_id: str,
                     current: dict = Depends(auth.get_current_user)):
    """Soft-delete a saved item."""
    conn = _users_conn()
    try:
        users.unsave_item(conn, user_id=current["user_id"], item_id=item_id)
        users.log_event(
            conn, user_id=current["user_id"],
            event_type="unsave", item_id=item_id,
        )
    finally:
        conn.close()
    return {"ok": True}
