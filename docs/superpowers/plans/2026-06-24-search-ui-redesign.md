# PLACSP Search UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bookmark-rail/drawer filter UI with a focused full-overlay "Filtros" workspace (Miller-column CPV explorer, Spain choropleth heatmap, density-backed range sliders, live results + count), restyle to a minimal "Institutional indigo" theme with Phosphor icons, move the relevance control to a colored right-side gutter, and add a Weaviate `Aggregate`-based `/api/facets` endpoint.

**Architecture:** Backend gains a pure `facets.py` module (mirroring `filters.py`) that builds aliased Weaviate `Aggregate` GraphQL in one round-trip, surfaced via `GET /api/facets`; `/api/search` returns a real `total`. Frontend extracts testable logic modules (`miller.js`, `density.js`, `geo/nuts.js`) consumed by new presentational components, all orchestrated by a rewritten `App.jsx` that drives a `FilterWorkspace` overlay. Spain geometry is fetched from Eurostat Nuts2json, filtered to `ES*`, and baked into the repo at build time.

**Tech Stack:** Python/FastAPI/httpx + Weaviate GraphQL (backend); React 18 + Vite + Vitest (frontend); new deps `@phosphor-icons/react`, `d3-geo`, `topojson-client` (build-time), `@testing-library/react` + `jsdom` (dev).

## Global Constraints

- Backend pure-logic modules (`filters.py`, `facets.py`) MUST stay stdlib-only (no FastAPI/httpx imports) so they unit-test without a running Weaviate.
- Weaviate class name comes from `CLASS` (env `PLACSP_CLASS`, default `Placsp_licitaciones`); never hard-code it.
- GraphQL enum values (operators, `order`, aggregation field selectors) MUST be unquoted; string values MUST be JSON-quoted. Follow the `filters._node_to_gql` pattern.
- NUTS codes: NUTS-2 (community) = 4 chars (e.g. `ES30`), NUTS-3 (province) = 5 chars (e.g. `ES300`). Spain prefix is `ES`.
- Filter state shape lives in `search-ui/src/filters.js` (`EMPTY`, `EXPLORE`); reuse it — do not invent a parallel shape.
- Existing feedback flow (`sendFeedback`/`removeFeedback`, session id, optimistic toggle) MUST keep working unchanged.
- Spanish UI copy throughout (match existing strings).
- Frontend tests use Vitest. Pure-logic tests need no DOM; component tests use `@testing-library/react` with the `jsdom` environment.
- Commit after every task with a `feat:`/`refactor:`/`chore:` message.

---

## File Structure

**Backend (`search-api/`):**
- Create `facets.py` — pure builders for Aggregate GraphQL + month-window logic (stdlib only).
- Create `test_facets.py` — unit tests for `facets.py`.
- Modify `search_api.py` — add `GET /api/facets`; add real `total` to `/api/search`.
- Modify `test_api_feedback.py`/add tests as needed for `total`.

**Geo build (`search-ui/`):**
- Create `scripts/build-spain-geo.mjs` — fetch Nuts2json, filter `ES*`, convert to GeoJSON, write to `src/geo/`.
- Create `src/geo/spain-nuts2.json`, `src/geo/spain-nuts3.json` — baked output (committed).

**Frontend logic modules (`search-ui/src/`):**
- Create `geo/nuts.js` (+ `geo/nuts.test.js`) — NUTS level/truncation/aggregation helpers.
- Create `density.js` (+ `density.test.js`) — scale + density-path + month-bucket helpers.
- Create `miller.js` (+ `miller.test.js`) — derive Miller columns from a selected path.
- Modify `api.js` (+ `api.test.js`) — add `facets()`.

**Frontend components (`search-ui/src/components/`):**
- Create `FilterWorkspace.jsx`, `CpvMiller.jsx`, `SpainMap.jsx`, `DensitySlider.jsx`, `LiveResults.jsx`.
- Create `src/icons.js` — central Phosphor re-exports.
- Modify `ResultCard.jsx`, `MultiCheck.jsx`, `ActiveFilters.jsx`, `App.jsx`, `styles.css`.
- Delete `FilterRail.jsx`, `FilterDrawer.jsx`, `CpvSelect.jsx`, `NutsSelect.jsx`, `RangeSlider.jsx`, `BudgetRange.jsx`, `DateTimeline.jsx`.

**Config:**
- Modify `package.json` (deps + scripts), create/modify `vite.config.js`/`vitest` config for jsdom.

---

## Task 1: Backend — `facets.py` total-count + groupBy builders

**Files:**
- Create: `search-api/facets.py`
- Test: `search-api/test_facets.py`

**Interfaces:**
- Consumes: `filters.where_to_gql`, `filters._node_to_gql` patterns (string GQL).
- Produces:
  - `agg_total(class_name: str, where: dict | None) -> str` — returns a GraphQL field string `total: <Class>(...) { meta { count } }`.
  - `agg_groupby(class_name: str, where: dict | None, prop: str) -> str` — returns `nuts: <Class>(..., groupBy: ["<prop>"]) { groupedBy { value } meta { count } }`.
  - `wrap_aggregate(fields: list[str]) -> str` — wraps field strings into `{ Aggregate { <fields...> } }`.

- [ ] **Step 1: Write the failing test**

```python
# search-api/test_facets.py
import facets as fac
import filters as filt


def test_agg_total_no_where():
    s = fac.agg_total("Placsp_licitaciones", None)
    assert s == "total: Placsp_licitaciones { meta { count } }"


def test_agg_total_with_where():
    where = filt.build_where(status=["PUB"])
    s = fac.agg_total("Placsp_licitaciones", where)
    assert s.startswith("total: Placsp_licitaciones(where: { path: [\"status_code\"]")
    assert s.endswith("{ meta { count } }")


def test_agg_groupby_nuts():
    s = fac.agg_groupby("Placsp_licitaciones", None, "nuts")
    assert s == ('nuts: Placsp_licitaciones(groupBy: ["nuts"]) '
                 "{ groupedBy { value } meta { count } }")


def test_agg_groupby_with_where_combines_args():
    where = filt.build_where(cpv=["45"])
    s = fac.agg_groupby("Placsp_licitaciones", where, "nuts")
    assert s.startswith('nuts: Placsp_licitaciones(where: { path: ["cpv"]')
    assert 'groupBy: ["nuts"]' in s


def test_wrap_aggregate():
    s = fac.wrap_aggregate(["total: X { meta { count } }"])
    assert s == "{ Aggregate { total: X { meta { count } } } }"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-api && python -m pytest test_facets.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'facets'`)

- [ ] **Step 3: Write minimal implementation**

```python
# search-api/facets.py
"""Pure builders for Weaviate Aggregate GraphQL (stdlib only, no FastAPI/httpx).

Mirrors filters.py: produces GraphQL *field* strings that the endpoint wraps in a
single { Aggregate { ... } } request using aliases, so total/nuts/month counts come
back in one round-trip. Kept dependency-free for unit testing without Weaviate.
"""
import filters as filt


def _args(where, extra=None):
    parts = []
    if where is not None:
        parts.append(filt.where_to_gql(where))  # "where: {...}"
    if extra:
        parts.append(extra)
    return f"({', '.join(parts)})" if parts else ""


def agg_total(class_name: str, where: dict | None) -> str:
    return f"total: {class_name}{_args(where)} {{ meta {{ count }} }}"


def agg_groupby(class_name: str, where: dict | None, prop: str) -> str:
    extra = f'groupBy: ["{prop}"]'
    return (f"nuts: {class_name}{_args(where, extra)} "
            "{ groupedBy { value } meta { count } }")


def wrap_aggregate(fields: list[str]) -> str:
    return "{ Aggregate { " + " ".join(fields) + " } }"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-api && python -m pytest test_facets.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add search-api/facets.py search-api/test_facets.py
git commit -m "feat: facets.py aggregate GraphQL builders (total + groupBy)"
```

---

## Task 2: Backend — `facets.py` month-window + per-month count builders

**Files:**
- Modify: `search-api/facets.py`
- Test: `search-api/test_facets.py`

**Interfaces:**
- Consumes: `filters.build_where`, `agg_total` (Task 1).
- Produces:
  - `month_buckets(from_date: str | None, to_date: str | None, cap: int = 36, today: date | None = None) -> list[dict]` — each `{"month": "YYYY-MM", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`, oldest→newest, at most `cap` months; defaults to the trailing `cap` months ending at `today` when no range given.
  - `agg_month_counts(class_name, base_where, date_field, buckets) -> list[str]` — one aliased `m{i}: <Class>(where: And(base, month-range)) { meta { count } }` field per bucket.

- [ ] **Step 1: Write the failing test**

```python
# append to search-api/test_facets.py
from datetime import date


def test_month_buckets_default_trailing_window():
    b = fac.month_buckets(None, None, cap=3, today=date(2026, 6, 15))
    assert [x["month"] for x in b] == ["2026-04", "2026-05", "2026-06"]
    assert b[0]["start"] == "2026-04-01"
    assert b[0]["end"] == "2026-04-30"
    assert b[2]["end"] == "2026-06-30"


def test_month_buckets_explicit_range_capped():
    b = fac.month_buckets("2020-01-01", "2026-06-30", cap=4, today=date(2026, 6, 15))
    assert len(b) == 4               # capped to most recent 4
    assert b[-1]["month"] == "2026-06"


def test_agg_month_counts_aliases_and_date_field():
    buckets = fac.month_buckets(None, None, cap=2, today=date(2026, 6, 15))
    fields = fac.agg_month_counts("Placsp_licitaciones", None, "publication_date", buckets)
    assert len(fields) == 2
    assert fields[0].startswith("m0: Placsp_licitaciones(where: {")
    assert "publication_date" in fields[0]
    assert "2026-05-01T00:00:00Z" in fields[0]
    assert "2026-05-31T23:59:59Z" in fields[0]
    assert fields[0].endswith("{ meta { count } }")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-api && python -m pytest test_facets.py -k "month" -v`
Expected: FAIL (`AttributeError: module 'facets' has no attribute 'month_buckets'`)

- [ ] **Step 3: Write minimal implementation**

```python
# add to search-api/facets.py
from calendar import monthrange
from datetime import date


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def month_buckets(from_date, to_date, cap: int = 36, today: date | None = None):
    today = today or date.today()
    end = date.fromisoformat(to_date) if to_date else today
    if from_date:
        start = date.fromisoformat(from_date)
    else:
        # trailing `cap` months ending at `end`
        y, m = end.year, end.month
        for _ in range(cap - 1):
            m = 12 if m == 1 else m - 1
            y = y - 1 if m == 12 else y
        start = date(y, m, 1)
    out = []
    for y, m in _month_iter(date(start.year, start.month, 1), end):
        last = monthrange(y, m)[1]
        out.append({
            "month": f"{y:04d}-{m:02d}",
            "start": f"{y:04d}-{m:02d}-01",
            "end": f"{y:04d}-{m:02d}-{last:02d}",
        })
    return out[-cap:]


def agg_month_counts(class_name, base_where, date_field, buckets):
    fields = []
    for i, b in enumerate(buckets):
        rng = filt.build_where(**{
            "pub_from": b["start"], "pub_to": b["end"],
        }) if date_field == "publication_date" else filt.build_where(**{
            "deadline_from": b["start"], "deadline_to": b["end"],
        })
        combined = rng if base_where is None else {
            "operator": "And", "operands": [base_where, rng]}
        fields.append(
            f"m{i}: {class_name}({filt.where_to_gql(combined)}) {{ meta {{ count }} }}")
    return fields
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-api && python -m pytest test_facets.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add search-api/facets.py search-api/test_facets.py
git commit -m "feat: facets month-window + per-month count builders"
```

---

## Task 3: Backend — `GET /api/facets` endpoint + real `total` on `/api/search`

**Files:**
- Modify: `search-api/search_api.py`
- Test: `search-api/test_facets_endpoint.py` (create)

**Interfaces:**
- Consumes: `facets.agg_total`, `facets.agg_groupby`, `facets.month_buckets`, `facets.agg_month_counts`, `facets.wrap_aggregate`; `filters.build_where`.
- Produces: `GET /api/facets` returning `{"total": int, "nuts": {code: count}, "dates": {"publication": [{month,count}], "plazo": [{month,count}]}}`; `/api/search` response gains `"total": int`.

Note: The endpoint builds ONE GraphQL request: `wrap_aggregate([agg_total, agg_groupby(nuts), *month_counts(pub), *month_counts(plazo)])`. Parse aliased results back out. Reuse `_wv_headers()` and the `httpx.post(... /v1/graphql ...)` pattern already in `search_api.py`.

- [ ] **Step 1: Write the failing test** (parsing helper is the unit-testable seam)

Add a pure parser to `facets.py` and test it (no HTTP needed):

```python
# append to search-api/test_facets.py
def test_parse_aggregate_response():
    raw = {"data": {"Aggregate": {
        "total": [{"meta": {"count": 1284}}],
        "nuts": [
            {"groupedBy": {"value": "ES300"}, "meta": {"count": 900}},
            {"groupedBy": {"value": "ES511"}, "meta": {"count": 384}},
        ],
        "m0": [{"meta": {"count": 10}}],
        "m1": [{"meta": {"count": 20}}],
    }}}
    pub = [{"month": "2026-05"}, {"month": "2026-06"}]
    out = fac.parse_aggregate(raw, pub_buckets=pub, plazo_buckets=[])
    assert out["total"] == 1284
    assert out["nuts"] == {"ES300": 900, "ES511": 384}
    assert out["dates"]["publication"] == [
        {"month": "2026-05", "count": 10}, {"month": "2026-06", "count": 20}]
    assert out["dates"]["plazo"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-api && python -m pytest test_facets.py -k parse -v`
Expected: FAIL (`has no attribute 'parse_aggregate'`)

- [ ] **Step 3: Implement `parse_aggregate` in `facets.py`**

```python
# add to search-api/facets.py
def parse_aggregate(raw: dict, pub_buckets, plazo_buckets) -> dict:
    agg = ((raw.get("data") or {}).get("Aggregate") or {})

    def _count(alias):
        node = agg.get(alias) or []
        return (node[0].get("meta", {}).get("count", 0)) if node else 0

    nuts = {}
    for g in (agg.get("nuts") or []):
        val = (g.get("groupedBy") or {}).get("value")
        if val:
            nuts[val] = g.get("meta", {}).get("count", 0)

    def _series(buckets, offset):
        return [{"month": b["month"], "count": _count(f"m{offset + i}")}
                for i, b in enumerate(buckets)]

    return {
        "total": _count("total"),
        "nuts": nuts,
        "dates": {
            "publication": _series(pub_buckets, 0),
            "plazo": _series(plazo_buckets, len(pub_buckets)),
        },
    }
```

- [ ] **Step 4: Run parser test to verify it passes**

Run: `cd search-api && python -m pytest test_facets.py -k parse -v`
Expected: PASS

- [ ] **Step 5: Wire the endpoint in `search_api.py`**

Add after the `/api/search` function:

```python
import facets as fac  # add near "import filters as filt"

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
    where = filt.build_where(
        cpv=cpv, nuts=nuts, status=status, result=result,
        contract_type=contract_type, procedure=procedure,
        pub_from=pub_from, pub_to=pub_to,
        deadline_from=deadline_from, deadline_to=deadline_to,
        budget_min=budget_min, budget_max=budget_max,
    )
    pub_b = fac.month_buckets(pub_from, pub_to, cap=36)
    plazo_b = fac.month_buckets(deadline_from, deadline_to, cap=36)
    fields = [
        fac.agg_total(CLASS, where),
        fac.agg_groupby(CLASS, where, "nuts"),
        *fac.agg_month_counts(CLASS, where, "publication_date", pub_b),
        *fac.agg_month_counts(CLASS, where, "submission_deadline", plazo_b),
    ]
    gql = fac.wrap_aggregate(fields)
    try:
        r = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": gql},
                       headers=_wv_headers(), timeout=120)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"weaviate error: {exc}")
    return fac.parse_aggregate(r.json(), pub_b, plazo_b)
```

Then add a real `total` to `/api/search`. In `search()`, after computing `where` and before/around the main query, return the aggregate total. Simplest: change the final return to include `total`. Add this near the end of `search()` (after `results` is built), running one extra aggregate count:

```python
    total = len(results)
    if where is not None or query:
        try:
            tg = fac.wrap_aggregate([fac.agg_total(CLASS, where)])
            tr = httpx.post(f"{WEAVIATE_URL}/v1/graphql", json={"query": tg},
                            headers=_wv_headers(), timeout=120)
            tr.raise_for_status()
            total = fac.parse_aggregate(tr.json(), [], [])["total"]
        except httpx.HTTPError:
            total = len(results)  # degrade: fall back to page size
    return {"query": q, "mode": mode, "count": len(results), "total": total,
            "offset": offset, "results": results, "errors": data.get("errors")}
```

- [ ] **Step 6: Smoke-test the endpoint builds valid GQL (no Weaviate)**

```python
# search-api/test_facets_endpoint.py
import facets as fac, filters as filt


def test_full_aggregate_query_is_single_request():
    where = filt.build_where(cpv=["45"], status=["PUB"])
    pub = fac.month_buckets("2026-01-01", "2026-03-31", cap=36)
    fields = [fac.agg_total("C", where), fac.agg_groupby("C", where, "nuts"),
              *fac.agg_month_counts("C", where, "publication_date", pub)]
    gql = fac.wrap_aggregate(fields)
    assert gql.count("{ Aggregate {") == 1
    assert "total:" in gql and "nuts:" in gql and "m0:" in gql
    assert '"And"' not in gql  # enums unquoted
```

Run: `cd search-api && python -m pytest test_facets_endpoint.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add search-api/search_api.py search-api/facets.py search-api/test_facets.py search-api/test_facets_endpoint.py
git commit -m "feat: /api/facets aggregate endpoint and real total on /api/search"
```

---

## Task 4: Geo — build script + baked Spain GeoJSON

**Files:**
- Create: `search-ui/scripts/build-spain-geo.mjs`
- Create (generated, committed): `search-ui/src/geo/spain-nuts2.json`, `search-ui/src/geo/spain-nuts3.json`
- Modify: `search-ui/package.json` (add `topojson-client` dev dep + `geo:build` script)

**Interfaces:**
- Produces: two GeoJSON `FeatureCollection`s where each feature has `id` = NUTS code (e.g. `ES30`) and `properties.name`. Consumed by `SpainMap.jsx` (Task 11).

- [ ] **Step 1: Add dependency and script entry**

```bash
cd search-ui && npm install --save-dev topojson-client
```

Add to `package.json` `"scripts"`: `"geo:build": "node scripts/build-spain-geo.mjs"`.

- [ ] **Step 2: Write the build script**

```javascript
// search-ui/scripts/build-spain-geo.mjs
// Fetch Eurostat Nuts2json (TopoJSON), filter to Spain (ES*), convert to GeoJSON,
// and write compact files baked into the app. Geometry rarely changes — run on demand.
import { writeFileSync, mkdirSync } from 'node:fs'
import { feature } from 'topojson-client'

const BASE = 'https://raw.githubusercontent.com/eurostat/Nuts2json/master/pub/v2/2024/4326/10M'
const OUT = new URL('../src/geo/', import.meta.url)
mkdirSync(OUT, { recursive: true })

async function build(level, outName) {
  const topo = await (await fetch(`${BASE}/${level}.json`)).json()
  const objName = Object.keys(topo.objects)[0]
  const fc = feature(topo, topo.objects[objName])
  fc.features = fc.features
    .filter((f) => String(f.id ?? f.properties?.id ?? '').startsWith('ES'))
    .map((f) => ({
      type: 'Feature',
      id: f.id ?? f.properties?.id,
      properties: { name: f.properties?.na ?? f.properties?.name ?? '' },
      geometry: f.geometry,
    }))
  writeFileSync(new URL(outName, OUT), JSON.stringify(fc))
  console.log(`${outName}: ${fc.features.length} ES features`)
}

await build('2', 'spain-nuts2.json')
await build('3', 'spain-nuts3.json')
```

- [ ] **Step 3: Run the build and verify output**

Run: `cd search-ui && npm run geo:build`
Expected: prints `spain-nuts2.json: ~19 ES features` and `spain-nuts3.json: ~59 ES features` (counts approximate). If the fetched file is already GeoJSON (not TopoJSON), adjust: detect `topo.type === 'Topology'` before calling `feature()`, else use `topo.features` directly. Verify files exist:

Run: `cd search-ui && node -e "const f=require('./src/geo/spain-nuts2.json'); console.log(f.type, f.features.length, f.features[0].id, f.features[0].properties.name)"`
Expected: `FeatureCollection 19 ES11 Galicia` (or similar)

- [ ] **Step 4: Commit**

```bash
git add search-ui/scripts/build-spain-geo.mjs search-ui/src/geo/spain-nuts2.json search-ui/src/geo/spain-nuts3.json search-ui/package.json search-ui/package-lock.json
git commit -m "feat: build + bake Spain NUTS GeoJSON from Eurostat Nuts2json"
```

---

## Task 5: Frontend — tooling (Phosphor, d3-geo, jsdom) + design tokens + `icons.js`

**Files:**
- Modify: `search-ui/package.json`
- Create/Modify: `search-ui/vite.config.js` (vitest jsdom env)
- Create: `search-ui/src/icons.js`
- Modify: `search-ui/src/styles.css` (design tokens only in this task)

**Interfaces:**
- Produces: named icon exports from `icons.js`; CSS custom properties for the indigo theme.

- [ ] **Step 1: Install dependencies**

```bash
cd search-ui && npm install @phosphor-icons/react d3-geo \
  && npm install --save-dev @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Configure Vitest jsdom environment**

Create or update `search-ui/vite.config.js`:

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test-setup.js' },
})
```

Create `search-ui/src/test-setup.js`:

```javascript
import '@testing-library/jest-dom'
```

- [ ] **Step 3: Create `icons.js`**

```javascript
// search-ui/src/icons.js — central Phosphor icon re-exports (one place to swap weights)
export {
  MagnifyingGlass, SlidersHorizontal, ThumbsUp, X, CaretRight, CaretDown,
  MapPin, Calendar, CurrencyEur, Stack, ListChecks, Scales, Gavel, Buildings,
} from '@phosphor-icons/react'
```

- [ ] **Step 4: Replace design tokens at top of `styles.css`**

Replace the `:root { ... }` block (lines 1-5) with:

```css
:root {
  --ink: #161a23; --muted: #6b7280; --line: #e7eaf1; --bg: #f7f8fb; --card: #fff;
  --accent: #4f46e5; --accent-soft: #eef0fe; --accent-ink: #4338ca;
  --chip: #eef1f6; --chip-ink: #4a5568; --ok: #1f7a4d; --ok-soft: #e9f7ef;
  --radius: 12px; --radius-sm: 9px; --shadow: 0 8px 30px rgba(22,26,35,.10);
  --font: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
```

Update `body { font: ... }` (line 7) to use `font-family: var(--font);` (keep size/line-height).

- [ ] **Step 5: Verify build still runs**

Run: `cd search-ui && npm run build`
Expected: build succeeds (no missing-module errors).

- [ ] **Step 6: Commit**

```bash
git add search-ui/package.json search-ui/package-lock.json search-ui/vite.config.js search-ui/src/test-setup.js search-ui/src/icons.js search-ui/src/styles.css
git commit -m "chore: add phosphor/d3-geo/jsdom, indigo design tokens, icons module"
```

---

## Task 6: Frontend logic — `geo/nuts.js`

**Files:**
- Create: `search-ui/src/geo/nuts.js`
- Test: `search-ui/src/geo/nuts.test.js`

**Interfaces:**
- Produces:
  - `nutsLevel(code: string) -> 2 | 3` (4 chars → 2, 5 chars → 3).
  - `truncate(code: string, level: 2 | 3) -> string` (level 2 → 4 chars, level 3 → 5 chars).
  - `aggregateByLevel(counts: Record<string,number>, level: 2|3) -> Record<string,number>` — sums fine-grained NUTS counts up to the requested level.
- Consumed by `SpainMap.jsx`.

- [ ] **Step 1: Write the failing test**

```javascript
// search-ui/src/geo/nuts.test.js
import { describe, it, expect } from 'vitest'
import { nutsLevel, truncate, aggregateByLevel } from './nuts.js'

describe('nuts helpers', () => {
  it('derives level from code length', () => {
    expect(nutsLevel('ES30')).toBe(2)
    expect(nutsLevel('ES300')).toBe(3)
  })
  it('truncates to a level', () => {
    expect(truncate('ES300', 2)).toBe('ES30')
    expect(truncate('ES300', 3)).toBe('ES300')
  })
  it('aggregates fine codes up to a level', () => {
    const counts = { ES300: 900, ES511: 100, ES512: 50 }
    expect(aggregateByLevel(counts, 2)).toEqual({ ES30: 900, ES51: 150 })
    expect(aggregateByLevel(counts, 3)).toEqual({ ES300: 900, ES511: 100, ES512: 50 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/geo/nuts.test.js`
Expected: FAIL (cannot resolve `./nuts.js`)

- [ ] **Step 3: Write minimal implementation**

```javascript
// search-ui/src/geo/nuts.js
export function nutsLevel(code) {
  return String(code).length >= 5 ? 3 : 2
}
export function truncate(code, level) {
  return String(code).slice(0, level === 2 ? 4 : 5)
}
export function aggregateByLevel(counts, level) {
  const out = {}
  for (const [code, n] of Object.entries(counts)) {
    const key = truncate(code, level)
    out[key] = (out[key] || 0) + n
  }
  return out
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/geo/nuts.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/geo/nuts.js search-ui/src/geo/nuts.test.js
git commit -m "feat: NUTS level/truncate/aggregate helpers"
```

---

## Task 7: Frontend logic — `density.js`

**Files:**
- Create: `search-ui/src/density.js`
- Test: `search-ui/src/density.test.js`

**Interfaces:**
- Produces:
  - `linearPos(value, min, max) -> number` in [0,1]; `linearValue(pos, min, max) -> number` (inverse).
  - `densityPath(values: number[], width: number, height: number) -> string` — an SVG path `d` for a smoothed (monotone) filled area; empty array → `''`.
- Consumed by `DensitySlider.jsx`. (Log scaling for budget reuses existing `budgetToPos`/`posToBudget` in `filters.js`.)

- [ ] **Step 1: Write the failing test**

```javascript
// search-ui/src/density.test.js
import { describe, it, expect } from 'vitest'
import { linearPos, linearValue, densityPath } from './density.js'

describe('density helpers', () => {
  it('maps value to [0,1] and back', () => {
    expect(linearPos(50, 0, 100)).toBeCloseTo(0.5)
    expect(linearValue(0.5, 0, 100)).toBeCloseTo(50)
  })
  it('clamps out-of-range positions', () => {
    expect(linearPos(-10, 0, 100)).toBe(0)
    expect(linearPos(200, 0, 100)).toBe(1)
  })
  it('returns empty path for no data', () => {
    expect(densityPath([], 100, 30)).toBe('')
  })
  it('builds a closed area path spanning the width', () => {
    const d = densityPath([1, 3, 2], 100, 30)
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d).toContain('100')           // reaches full width
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/density.test.js`
Expected: FAIL (cannot resolve `./density.js`)

- [ ] **Step 3: Write minimal implementation**

```javascript
// search-ui/src/density.js
export function linearPos(value, min, max) {
  if (max <= min) return 0
  return Math.max(0, Math.min(1, (value - min) / (max - min)))
}
export function linearValue(pos, min, max) {
  return min + Math.max(0, Math.min(1, pos)) * (max - min)
}

// Smoothed filled area for a sparkline-style density. Uses a simple Catmull-Rom-ish
// midpoint smoothing — quiet and good enough for a subtle backdrop.
export function densityPath(values, width, height) {
  const n = values.length
  if (n === 0) return ''
  const max = Math.max(...values, 1)
  const xs = (i) => (n === 1 ? width : (i / (n - 1)) * width)
  const ys = (v) => height - (v / max) * height
  let d = `M0 ${ys(values[0]).toFixed(2)}`
  for (let i = 1; i < n; i++) {
    const xm = ((xs(i - 1) + xs(i)) / 2).toFixed(2)
    d += ` Q${xm} ${ys(values[i - 1]).toFixed(2)} ${xs(i).toFixed(2)} ${ys(values[i]).toFixed(2)}`
  }
  d += ` L${width} ${height} L0 ${height} Z`
  return d
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/density.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/density.js search-ui/src/density.test.js
git commit -m "feat: density scale + smoothed area-path helpers"
```

---

## Task 8: Frontend logic — `miller.js`

**Files:**
- Create: `search-ui/src/miller.js`
- Test: `search-ui/src/miller.test.js`

**Interfaces:**
- Consumes: `cpv.js` (`cpvChildren`, `cpvLevel`), `cpvMap`.
- Produces: `columns(path: string[], cpvMap) -> Array<{ items: Array<{code,label}>, activeCode: string | null }>` — column 0 is the CPV divisions; each subsequent column holds the children of the active code in the previous column. `path` is the list of drilled-into codes.
- Consumed by `CpvMiller.jsx`.

- [ ] **Step 1: Write the failing test**

```javascript
// search-ui/src/miller.test.js
import { describe, it, expect } from 'vitest'
import { columns } from './miller.js'

const MAP = {
  '45': 'Construcción', '72': 'TI',
  '4500': 'Construcción general', '4521': 'Edificios',
  '452100': 'Trabajos de edificios',
}

describe('miller columns', () => {
  it('column 0 lists divisions (2-digit) sorted', () => {
    const cols = columns([], MAP)
    expect(cols).toHaveLength(1)
    expect(cols[0].items.map((i) => i.code)).toEqual(['45', '72'])
    expect(cols[0].activeCode).toBe(null)
  })
  it('drilling adds a child column and marks the active code', () => {
    const cols = columns(['45'], MAP)
    expect(cols).toHaveLength(2)
    expect(cols[0].activeCode).toBe('45')
    expect(cols[1].items.map((i) => i.code)).toContain('4500')
    expect(cols[1].items.map((i) => i.code)).toContain('4521')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/miller.test.js`
Expected: FAIL (cannot resolve `./miller.js`)

- [ ] **Step 3: Write minimal implementation**

```javascript
// search-ui/src/miller.js
import { cpvChildren, cpvLevel } from './cpv.js'

function divisions(cpvMap) {
  return Object.keys(cpvMap).filter((c) => cpvLevel(c) === 2).sort()
}

export function columns(path, cpvMap) {
  const cols = []
  let codes = divisions(cpvMap)
  for (let depth = 0; ; depth++) {
    const activeCode = path[depth] ?? null
    cols.push({
      items: codes.map((code) => ({ code, label: cpvMap[code] || '—' })),
      activeCode,
    })
    if (activeCode == null) break
    const kids = cpvChildren(activeCode, cpvMap)
    if (kids.length === 0) break
    codes = kids
  }
  return cols
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/miller.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/miller.js search-ui/src/miller.test.js
git commit -m "feat: derive CPV Miller columns from a drilled path"
```

---

## Task 9: Frontend — `api.js` `facets()`

**Files:**
- Modify: `search-ui/src/api.js`
- Test: `search-ui/src/api.test.js`

**Interfaces:**
- Produces: `facets(params) -> Promise<{total, nuts, dates}>` calling `GET {BASE}/api/facets?<buildQuery(params)>`.
- Consumes existing `buildQuery`, `BASE`.

- [ ] **Step 1: Write the failing test** (mock `fetch`)

```javascript
// add to search-ui/src/api.test.js
import { describe, it, expect, vi, afterEach } from 'vitest'
import { facets } from './api.js'

afterEach(() => vi.restoreAllMocks())

describe('facets()', () => {
  it('GETs /api/facets with serialized params and returns json', async () => {
    const body = { total: 5, nuts: { ES30: 5 }, dates: { publication: [], plazo: [] } }
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      { ok: true, json: () => Promise.resolve(body) })
    const out = await facets({ cpv: ['45'], status: ['PUB'] })
    expect(out).toEqual(body)
    const url = spy.mock.calls[0][0]
    expect(url).toContain('/api/facets?')
    expect(url).toContain('cpv=45')
    expect(url).toContain('status=PUB')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/api.test.js`
Expected: FAIL (`facets` is not exported)

- [ ] **Step 3: Implement `facets` in `api.js`**

```javascript
// add to search-ui/src/api.js
export async function facets(params) {
  const url = `${BASE}/api/facets?${buildQuery(params)}`
  const r = await fetch(url)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/api.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/api.js search-ui/src/api.test.js
git commit -m "feat: api.facets() client"
```

---

## Task 10: Frontend — `ResultCard` restyle + right-side colored relevance gutter

**Files:**
- Modify: `search-ui/src/components/ResultCard.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/ResultCard.test.jsx`

**Interfaces:**
- Unchanged props: `{ r, liked, onToggleLike }`. Visual change only: relevance becomes a full-height right gutter (Phosphor `ThumbsUp`).

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/ResultCard.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ResultCard from './ResultCard.jsx'

const R = { title: 'Limpieza', contracting_authority: 'Ayto', cpv: ['90910000'] }

describe('ResultCard relevance gutter', () => {
  it('renders the relevance button and toggles', () => {
    const onToggle = vi.fn()
    render(<ResultCard r={R} liked={false} onToggleLike={onToggle} />)
    const btn = screen.getByRole('button', { name: /relevante/i })
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenCalled()
  })
  it('reflects liked state via aria-pressed', () => {
    render(<ResultCard r={R} liked onToggleLike={() => {}} />)
    expect(screen.getByRole('button', { name: /relevante/i })).toHaveAttribute('aria-pressed', 'true')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/ResultCard.test.jsx`
Expected: FAIL (current button label is `¿Relevante?`/`Relevante` but layout differs; if it passes by accident, proceed — the restyle is still required)

- [ ] **Step 3: Restructure `ResultCard.jsx`**

Wrap the existing body in a flex card with a right gutter. Replace the `return (...)` so the structure is:

```jsx
import { money } from '../format.js'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import { ThumbsUp } from '../icons.js'

export default function ResultCard({ r, liked = false, onToggleLike = () => {} }) {
  const title = r.title || r.expediente || r.syndication_id || 'Sin título'
  const moneys = [
    ['Presupuesto', r.budget_amount],
    ['Valor estimado', r.estimated_value],
    ['Adjudicación', r.awarded_amount],
  ].map(([label, v]) => [label, money(v)]).filter(([, v]) => v)
  const nutsLabel = r.nuts_label || nutsMap[r.nuts] || r.city
  const loc = [nutsLabel, r.publication_date].filter(Boolean).join(' · ')

  return (
    <div className="card">
      <div className="card-main">
        {r._score != null && <span className="score">{Number(r._score).toFixed(3)}</span>}
        <div className="badges">
          {r.category && <span className="badge">{r.category}</span>}
          {r.contract_type && <span className="badge">{r.contract_type}</span>}
          {r.status_label && <span className="badge estado">{r.status_label}</span>}
        </div>
        <h2>{r.source_url
          ? <a href={r.source_url} target="_blank" rel="noopener noreferrer">{title}</a>
          : title}</h2>
        {r.contracting_authority && (
          <div className="row"><b>Órgano:</b> {r.contracting_authority}
            {r.org_top_level && r.org_top_level !== r.contracting_authority && ` · ${r.org_top_level}`}</div>
        )}
        {r.procedure && <div className="row"><b>Procedimiento:</b> {r.procedure}</div>}
        {moneys.length > 0 && (
          <div className="money">{moneys.map(([label, v]) => (
            <span key={label}><b>{label}:</b> {v}</span>))}</div>
        )}
        {Array.isArray(r.cpv) && r.cpv.length > 0 && (
          <div className="chips">{r.cpv.slice(0, 8).map((c) => (
            <span className="chip" key={c} title={cpvMap[c] || ''}>
              {c}{cpvMap[c] ? ` · ${cpvMap[c]}` : ''}</span>))}</div>
        )}
        {r.adjudicatario && <div className="row"><b>Adjudicatario:</b> {r.adjudicatario}</div>}
        {loc && <div className="row">{loc}</div>}
        {r.content && <div className="snippet">{r.content}</div>}
      </div>
      <button
        type="button"
        className={`relgutter${liked ? ' on' : ''}`}
        onClick={onToggleLike}
        aria-pressed={liked}
        title={liked ? 'Marcado como relevante' : 'Marcar como relevante'}
      >
        <ThumbsUp size={20} weight={liked ? 'fill' : 'regular'} />
        <span>Relevante</span>
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Add styles** to `styles.css` (replace the `.card` rule and the old `.card-foot`/`.like` rules):

```css
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 12px; display: flex; overflow: hidden; }
.card-main { padding: 16px 18px; flex: 1; min-width: 0; }
.relgutter { flex: 0 0 64px; border: none; border-left: 1px solid var(--line); background: #fff; color: var(--muted); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; font-size: 11px; font-weight: 600; cursor: pointer; }
.relgutter:hover { background: var(--accent-soft); color: var(--accent); }
.relgutter.on { background: var(--accent); color: #fff; border-left-color: var(--accent); }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/ResultCard.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/components/ResultCard.jsx search-ui/src/components/ResultCard.test.jsx search-ui/src/styles.css
git commit -m "feat: result card restyle with right-side relevance gutter"
```

---

## Task 11: Frontend — `DensitySlider` component

**Files:**
- Create: `search-ui/src/components/DensitySlider.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/DensitySlider.test.jsx`

**Interfaces:**
- Consumes: `density.js` (`densityPath`, `linearPos`, `linearValue`).
- Produces: `DensitySlider({ min, max, low, high, density = [], onChange, format, toPos, toValue })` where `toPos`/`toValue` default to linear (`linearPos`/`linearValue`); budget passes log versions from `filters.js`. Renders an SVG density backdrop + two range inputs; calls `onChange({ low, high })`.

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/DensitySlider.test.jsx
import { describe, it, expect } from 'vitest'
import { render, container as _c } from '@testing-library/react'
import DensitySlider from './DensitySlider.jsx'

describe('DensitySlider', () => {
  it('renders two range inputs and a density path', () => {
    const { container } = render(
      <DensitySlider min={0} max={100} low={20} high={80}
        density={[1, 4, 2, 5]} onChange={() => {}} />)
    expect(container.querySelectorAll('input[type=range]')).toHaveLength(2)
    expect(container.querySelector('svg path')).toBeTruthy()
  })
  it('omits the density path when no data', () => {
    const { container } = render(
      <DensitySlider min={0} max={100} low={0} high={100} density={[]} onChange={() => {}} />)
    const p = container.querySelector('svg path')
    expect(p?.getAttribute('d') || '').toBe('')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/DensitySlider.test.jsx`
Expected: FAIL (cannot resolve component)

- [ ] **Step 3: Implement `DensitySlider.jsx`**

```jsx
import { densityPath, linearPos, linearValue } from '../density.js'

const W = 1000, H = 40

export default function DensitySlider({
  min, max, low, high, density = [], onChange,
  format = (v) => v, toPos = linearPos, toValue = linearValue,
}) {
  const d = densityPath(density, W, H)
  const lowPos = toPos(low, min, max), highPos = toPos(high, min, max)
  const set = (which, pos) => {
    const v = Math.round(toValue(pos, min, max))
    onChange(which === 'low' ? { low: Math.min(v, high), high } : { low, high: Math.max(v, low) })
  }
  return (
    <div className="density-slider">
      <svg className="density-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path d={d} className="density-area" />
      </svg>
      <div className="ds-track">
        <div className="ds-fill" style={{ left: `${lowPos * 100}%`, right: `${(1 - highPos) * 100}%` }} />
        <input type="range" min="0" max="1" step="0.001" value={lowPos}
          onChange={(e) => set('low', Number(e.target.value))} className="ds-thumb" />
        <input type="range" min="0" max="1" step="0.001" value={highPos}
          onChange={(e) => set('high', Number(e.target.value))} className="ds-thumb" />
      </div>
      <div className="ds-labels"><span>{format(low)}</span><span>{format(high)}</span></div>
    </div>
  )
}
```

- [ ] **Step 4: Add styles** to `styles.css`:

```css
.density-slider { margin: 10px 2px; }
.density-svg { width: 100%; height: 40px; display: block; }
.density-area { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 1; opacity: .55; }
.ds-track { position: relative; height: 24px; }
.ds-track::before { content: ""; position: absolute; top: 11px; left: 0; right: 0; height: 3px; background: var(--line); border-radius: 3px; }
.ds-fill { position: absolute; top: 11px; height: 3px; background: var(--accent); border-radius: 3px; }
.ds-thumb { position: absolute; top: 0; left: 0; width: 100%; margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
.ds-thumb::-webkit-slider-thumb { pointer-events: auto; -webkit-appearance: none; height: 18px; width: 18px; border-radius: 50%; background: #fff; border: 2px solid var(--accent); cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.2); }
.ds-thumb::-moz-range-thumb { pointer-events: auto; height: 18px; width: 18px; border-radius: 50%; background: #fff; border: 2px solid var(--accent); cursor: pointer; }
.ds-labels { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-top: 4px; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/DensitySlider.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/components/DensitySlider.jsx search-ui/src/components/DensitySlider.test.jsx search-ui/src/styles.css
git commit -m "feat: DensitySlider (dual handle + subtle density area)"
```

---

## Task 12: Frontend — `CpvMiller` component

**Files:**
- Create: `search-ui/src/components/CpvMiller.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/CpvMiller.test.jsx`

**Interfaces:**
- Consumes: `miller.js` `columns`, `cpv.js` helpers, `cpvMap`, `icons.js`.
- Produces: `CpvMiller({ value: string[], onChange })` — search box + Miller columns + selected chips. `value`/`onChange` mirror today's `CpvSelect` (array of codes).

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/CpvMiller.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CpvMiller from './CpvMiller.jsx'

describe('CpvMiller', () => {
  it('shows division column and a search box', () => {
    render(<CpvMiller value={[]} onChange={() => {}} />)
    expect(screen.getByPlaceholderText(/buscar/i)).toBeInTheDocument()
  })
  it('renders selected codes as chips with remove', () => {
    const onChange = vi.fn()
    render(<CpvMiller value={['45000000']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /quitar/i }))
    expect(onChange).toHaveBeenCalledWith([])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/CpvMiller.test.jsx`
Expected: FAIL (cannot resolve component)

- [ ] **Step 3: Implement `CpvMiller.jsx`**

```jsx
import { useMemo, useState } from 'react'
import cpvMap from '../codelists/cpv.json'
import { columns } from '../miller.js'
import { cpvPath } from '../cpv.js'
import { MagnifyingGlass, CaretRight, X } from '../icons.js'

const ENTRIES = Object.entries(cpvMap)

export default function CpvMiller({ value, onChange }) {
  const [path, setPath] = useState([])
  const [term, setTerm] = useState('')

  const cols = useMemo(() => columns(path, cpvMap), [path])
  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.startsWith(t) || label.toLowerCase().includes(t)) out.push([code, label])
      if (out.length >= 40) break
    }
    return out
  }, [term])

  const add = (code) => { if (!value.includes(code)) onChange([...value, code]); setTerm('') }
  const remove = (code) => onChange(value.filter((c) => c !== code))
  const drill = (depth, code) => setPath([...path.slice(0, depth), code])

  return (
    <div className="cpv-miller">
      <div className="cm-search">
        <MagnifyingGlass size={16} />
        <input type="search" value={term} onChange={(e) => setTerm(e.target.value)}
          placeholder="Buscar CPV: código o descripción" />
      </div>
      {matches.length > 0 ? (
        <ul className="cm-matches">
          {matches.map(([code, label]) => (
            <li key={code} onClick={() => add(code)}>
              <span className="cpv-code">{code}</span> · {label}
              {cpvPath(code, cpvMap).length > 0 && (
                <div className="cpv-path">{cpvPath(code, cpvMap).join(' › ')}</div>)}
            </li>
          ))}
        </ul>
      ) : (
        <div className="cm-cols">
          {cols.map((col, depth) => (
            <div className="cm-col" key={depth}>
              {col.items.map(({ code, label }) => (
                <div key={code}
                  className={`cm-item${col.activeCode === code ? ' path' : ''}`}
                  onClick={() => drill(depth, code)}>
                  <span className="cm-label"><span className="cpv-code">{code}</span> {label}</span>
                  <button type="button" className="cm-add" aria-label="Añadir"
                    onClick={(e) => { e.stopPropagation(); add(code) }}>+</button>
                  <CaretRight size={12} />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {value.length > 0 && (
        <div className="cm-chips">
          {value.map((code) => (
            <span className="chip" key={code}>
              {code} · {cpvMap[code] || '—'}
              <button type="button" aria-label="Quitar" onClick={() => remove(code)}><X size={11} /></button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Add styles** to `styles.css`:

```css
.cm-search { display: flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 8px 10px; color: var(--muted); }
.cm-search input { border: none; outline: none; flex: 1; font-size: 14px; }
.cm-cols { display: flex; gap: 0; margin-top: 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; min-height: 220px; }
.cm-col { flex: 1; border-right: 1px solid var(--line); overflow-y: auto; max-height: 320px; }
.cm-col:last-child { border-right: none; }
.cm-item { display: flex; align-items: center; gap: 6px; padding: 6px 8px; cursor: pointer; font-size: 13px; }
.cm-item:hover { background: var(--accent-soft); }
.cm-item.path { background: var(--accent-soft); color: var(--accent-ink); }
.cm-label { flex: 1; min-width: 0; }
.cm-add { border: 1px solid var(--line); background: #fff; border-radius: 6px; color: var(--accent); width: 20px; height: 20px; padding: 0; }
.cm-matches { list-style: none; margin: 10px 0 0; padding: 0; max-height: 320px; overflow: auto; border: 1px solid var(--line); border-radius: var(--radius-sm); }
.cm-matches li { padding: 7px 9px; cursor: pointer; font-size: 13px; }
.cm-matches li:hover { background: var(--accent-soft); }
.cm-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/CpvMiller.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/components/CpvMiller.jsx search-ui/src/components/CpvMiller.test.jsx search-ui/src/styles.css
git commit -m "feat: CpvMiller column explorer with search"
```

---

## Task 13: Frontend — `SpainMap` component

**Files:**
- Create: `search-ui/src/components/SpainMap.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/SpainMap.test.jsx`

**Interfaces:**
- Consumes: `d3-geo` (`geoMercator`, `geoPath`), `geo/nuts.js` (`aggregateByLevel`, `truncate`), `geo/spain-nuts2.json`, `geo/spain-nuts3.json`, `icons.js`.
- Produces: `SpainMap({ value: string[], counts: Record<string,number>, onChange })` — `value` selected NUTS codes, `counts` per-region from facets. Renders toggle (Comunidades/Provincias) + SVG choropleth; clicking a region toggles it in `value`.

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/SpainMap.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SpainMap from './SpainMap.jsx'

describe('SpainMap', () => {
  it('renders a level toggle and svg paths', () => {
    const { container } = render(<SpainMap value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /comunidades/i })).toBeInTheDocument()
    expect(container.querySelectorAll('svg path').length).toBeGreaterThan(0)
  })
  it('toggles a region on click', () => {
    const onChange = vi.fn()
    const { container } = render(<SpainMap value={[]} counts={{}} onChange={onChange} />)
    fireEvent.click(container.querySelector('svg path'))
    expect(onChange).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/SpainMap.test.jsx`
Expected: FAIL (cannot resolve component)

- [ ] **Step 3: Implement `SpainMap.jsx`**

```jsx
import { useMemo, useState } from 'react'
import { geoMercator, geoPath } from 'd3-geo'
import nuts2 from '../geo/spain-nuts2.json'
import nuts3 from '../geo/spain-nuts3.json'
import { aggregateByLevel } from '../geo/nuts.js'

const W = 460, H = 360

function shade(n, max) {
  if (!n) return 'var(--bg)'
  const t = Math.min(1, Math.log(n + 1) / Math.log(max + 1))
  const steps = ['#eef2f7', '#cfe0f3', '#9cc1e8', '#5b94d6', '#2f6fc0']
  return steps[Math.min(steps.length - 1, Math.floor(t * steps.length))]
}

export default function SpainMap({ value, counts, onChange }) {
  const [level, setLevel] = useState(2)
  const fc = level === 2 ? nuts2 : nuts3
  const byLevel = useMemo(() => aggregateByLevel(counts || {}, level), [counts, level])
  const max = Math.max(1, ...Object.values(byLevel))

  const path = useMemo(() => {
    const proj = geoMercator().fitSize([W, H], fc)
    return geoPath(proj)
  }, [fc])

  const toggle = (id) => onChange(
    value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <div className="spain-map">
      <div className="sm-toggle">
        <button type="button" className={level === 2 ? 'on' : ''} onClick={() => setLevel(2)}>Comunidades</button>
        <button type="button" className={level === 3 ? 'on' : ''} onClick={() => setLevel(3)}>Provincias</button>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="sm-svg">
        {fc.features.map((f) => (
          <path key={f.id} d={path(f)}
            className={`sm-region${value.includes(f.id) ? ' sel' : ''}`}
            fill={shade(byLevel[f.id], max)}
            onClick={() => toggle(f.id)}>
            <title>{f.properties.name} · {byLevel[f.id] || 0}</title>
          </path>
        ))}
      </svg>
      <div className="sm-list">
        {value.map((id) => {
          const f = fc.features.find((x) => x.id === id)
          return <span className="chip" key={id}>{f ? f.properties.name : id}
            <button type="button" aria-label="Quitar" onClick={() => toggle(id)}>✕</button></span>
        })}
      </div>
    </div>
  )
}
```

Note: when switching levels, selected codes of the other level remain in `value`; that is acceptable (they still filter via NUTS prefix). The backend `_prefix("nuts", ...)` makes a community code match its provinces.

- [ ] **Step 4: Add styles** to `styles.css`:

```css
.sm-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; margin-bottom: 10px; }
.sm-toggle button { border: none; background: #fff; color: var(--muted); padding: 5px 14px; font-size: 12px; font-weight: 600; }
.sm-toggle button.on { background: var(--ink); color: #fff; }
.sm-svg { width: 100%; max-width: 460px; height: auto; display: block; }
.sm-region { stroke: #fff; stroke-width: .5; cursor: pointer; transition: opacity .1s; }
.sm-region:hover { opacity: .8; }
.sm-region.sel { stroke: var(--ok); stroke-width: 2; }
.sm-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/SpainMap.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/components/SpainMap.jsx search-ui/src/components/SpainMap.test.jsx search-ui/src/styles.css
git commit -m "feat: SpainMap choropleth with community/province toggle"
```

---

## Task 14: Frontend — `MultiCheck` restyle + `LiveResults` component

**Files:**
- Modify: `search-ui/src/components/MultiCheck.jsx`
- Create: `search-ui/src/components/LiveResults.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/LiveResults.test.jsx`

**Interfaces:**
- `MultiCheck` keeps its current props `{ map, value, onChange }` — restyle only (no API change).
- `LiveResults({ total, results, loading })` — renders the live total count + a compact preview list (title + authority). `results` is the `state.data.results` array.

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/LiveResults.test.jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import LiveResults from './LiveResults.jsx'

describe('LiveResults', () => {
  it('shows the total and preview titles', () => {
    render(<LiveResults total={1284} loading={false}
      results={[{ syndication_id: '1', title: 'Limpieza' }]} />)
    expect(screen.getByText(/1\.?284/)).toBeInTheDocument()
    expect(screen.getByText('Limpieza')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/LiveResults.test.jsx`
Expected: FAIL (cannot resolve component)

- [ ] **Step 3: Implement `LiveResults.jsx`**

```jsx
export default function LiveResults({ total, results = [], loading = false }) {
  return (
    <aside className="live-results">
      <div className={`lr-count${loading ? ' loading' : ''}`}>
        {total != null ? total.toLocaleString('es-ES') : '—'} <span>resultados</span>
      </div>
      <div className="lr-list">
        {results.slice(0, 8).map((r) => (
          <div className="lr-item" key={r._id || r.syndication_id}>
            <div className="lr-title">{r.title || r.expediente || 'Sin título'}</div>
            {r.contracting_authority && <div className="lr-auth">{r.contracting_authority}</div>}
          </div>
        ))}
      </div>
    </aside>
  )
}
```

- [ ] **Step 4: Add styles** to `styles.css` (LiveResults + MultiCheck refresh). Replace the `.checks`/`.check` rules:

```css
.live-results { display: flex; flex-direction: column; gap: 10px; }
.lr-count { font-size: 20px; font-weight: 700; color: var(--ok); }
.lr-count span { font-size: 12px; font-weight: 500; color: var(--muted); }
.lr-count.loading { opacity: .5; }
.lr-list { display: flex; flex-direction: column; gap: 8px; overflow: auto; }
.lr-item { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.lr-title { font-size: 12.5px; font-weight: 600; line-height: 1.3; }
.lr-auth { font-size: 11px; color: var(--muted); margin-top: 2px; }
.checks { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow: auto; }
.check { display: flex; gap: 8px; align-items: center; font-size: 14px; padding: 6px 8px; border-radius: 8px; }
.check:hover { background: var(--accent-soft); }
```

- [ ] **Step 5: Apply a light restyle to `MultiCheck.jsx`** — ensure each row uses `className="check"` (it likely already does). Read the file; if rows already use `.check`, no JSX change is needed and this step is just verification. Confirm by running its existing usage.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/LiveResults.test.jsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add search-ui/src/components/LiveResults.jsx search-ui/src/components/MultiCheck.jsx search-ui/src/components/LiveResults.test.jsx search-ui/src/styles.css
git commit -m "feat: LiveResults preview column + MultiCheck restyle"
```

---

## Task 15: Frontend — `FilterWorkspace` shell

**Files:**
- Create: `search-ui/src/components/FilterWorkspace.jsx`
- Modify: `search-ui/src/styles.css`
- Test: `search-ui/src/components/FilterWorkspace.test.jsx`

**Interfaces:**
- Consumes: `CpvMiller`, `SpainMap`, `DensitySlider`, `MultiCheck`, `LiveResults`, `icons.js`, `filters.js`, codelists, `posToBudget`/`budgetToPos`.
- Produces: `FilterWorkspace({ filters, patch, setList, facetsData, total, previewResults, loading, onClose })`. Renders the three-zone overlay: category list (left), active rich view (center), `LiveResults` (right). Internal state = active category.

Category → center view mapping:
- `cpv` → `<CpvMiller value={filters.cpv} onChange={(v) => setList('cpv', v)} />`
- `nuts` → `<SpainMap value={filters.nuts} counts={facetsData?.nuts || {}} onChange={(v) => setList('nuts', v)} />`
- `dates` → `<DensitySlider .../>` over publication/plazo (axis switch + presets), writing `pub_from/pub_to` or `deadline_from/deadline_to` via `patch`.
- `budget` → `<DensitySlider toPos={budgetToPos} toValue={posToBudget} .../>` writing `budget_min/budget_max`.
- `status`/`result`/`contract_type`/`procedure` → `<MultiCheck .../>`.

- [ ] **Step 1: Write the failing component test**

```javascript
// search-ui/src/components/FilterWorkspace.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FilterWorkspace from './FilterWorkspace.jsx'
import { EMPTY } from '../filters.js'

const base = {
  filters: EMPTY, patch: () => {}, setList: () => {},
  facetsData: { nuts: {}, dates: { publication: [], plazo: [] } },
  total: 42, previewResults: [], loading: false,
}

describe('FilterWorkspace', () => {
  it('shows category list, live count, and closes', () => {
    const onClose = vi.fn()
    render(<FilterWorkspace {...base} onClose={onClose} />)
    expect(screen.getByRole('button', { name: /CPV/i })).toBeInTheDocument()
    expect(screen.getByText(/42/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /cerrar/i }))
    expect(onClose).toHaveBeenCalled()
  })
  it('switches the center pane when a category is chosen', () => {
    render(<FilterWorkspace {...base} onClose={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /ubicación/i }))
    expect(screen.getByRole('button', { name: /comunidades/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/FilterWorkspace.test.jsx`
Expected: FAIL (cannot resolve component)

- [ ] **Step 3: Implement `FilterWorkspace.jsx`**

```jsx
import { useState } from 'react'
import CpvMiller from './CpvMiller.jsx'
import SpainMap from './SpainMap.jsx'
import DensitySlider from './DensitySlider.jsx'
import MultiCheck from './MultiCheck.jsx'
import LiveResults from './LiveResults.jsx'
import { budgetToPos, posToBudget, presetRange, todayISO } from '../filters.js'
import { money } from '../format.js'
import { Stack, MapPin, Calendar, CurrencyEur, ListChecks, Scales, Gavel, Buildings, X } from '../icons.js'
import statusMap from '../codelists/status.json'
import resultMap from '../codelists/result.json'
import typeMap from '../codelists/contract_type.json'
import procMap from '../codelists/procedure.json'

const CATS = [
  { id: 'cpv', label: 'CPV', Icon: Stack, fields: ['cpv'] },
  { id: 'nuts', label: 'Ubicación', Icon: MapPin, fields: ['nuts'] },
  { id: 'dates', label: 'Fechas', Icon: Calendar, fields: ['pub_from', 'pub_to', 'deadline_from'] },
  { id: 'budget', label: 'Presupuesto', Icon: CurrencyEur, fields: ['budget_min', 'budget_max'] },
  { id: 'status', label: 'Estado', Icon: ListChecks, fields: ['status'] },
  { id: 'result', label: 'Resultado', Icon: ListChecks, fields: ['result'] },
  { id: 'contract_type', label: 'Tipo', Icon: Scales, fields: ['contract_type'] },
  { id: 'procedure', label: 'Procedimiento', Icon: Gavel, fields: ['procedure'] },
]

function catCount(cat, f) {
  if (cat.id === 'cpv' || ['nuts', 'status', 'result', 'contract_type', 'procedure'].includes(cat.id))
    return (f[cat.id] || []).length
  if (cat.id === 'dates') return (f.pub_from || f.pub_to || f.deadline_from) ? 1 : 0
  if (cat.id === 'budget') return (f.budget_min || f.budget_max) ? 1 : 0
  return 0
}

export default function FilterWorkspace({ filters, patch, setList, facetsData, total, previewResults, loading, onClose }) {
  const [active, setActive] = useState('cpv')
  const [dateAxis, setDateAxis] = useState('publication')

  const center = () => {
    switch (active) {
      case 'cpv': return <CpvMiller value={filters.cpv} onChange={(v) => setList('cpv', v)} />
      case 'nuts': return <SpainMap value={filters.nuts} counts={facetsData?.nuts || {}} onChange={(v) => setList('nuts', v)} />
      case 'status': return <MultiCheck map={statusMap} value={filters.status} onChange={(v) => setList('status', v)} />
      case 'result': return <MultiCheck map={resultMap} value={filters.result} onChange={(v) => setList('result', v)} />
      case 'contract_type': return <MultiCheck map={typeMap} value={filters.contract_type} onChange={(v) => setList('contract_type', v)} />
      case 'procedure': return <MultiCheck map={procMap} value={filters.procedure} onChange={(v) => setList('procedure', v)} />
      case 'budget': {
        const lo = Number(filters.budget_min) || 1000
        const hi = Number(filters.budget_max) || 100000000
        return <DensitySlider min={1000} max={100000000} low={lo} high={hi}
          density={(facetsData?.budget || []).map((b) => b.count)}
          toPos={budgetToPos} toValue={posToBudget} format={(v) => money(v)}
          onChange={({ low, high }) => patch({ budget_min: String(low), budget_max: String(high) })} />
      }
      case 'dates': {
        const series = (facetsData?.dates?.[dateAxis] || [])
        const months = series.map((s) => s.month)
        const lo = 0, hi = Math.max(0, months.length - 1)
        return (
          <div>
            <div className="ws-axis">
              <button className={dateAxis === 'publication' ? 'on' : ''} onClick={() => setDateAxis('publication')}>Publicación</button>
              <button className={dateAxis === 'plazo' ? 'on' : ''} onClick={() => setDateAxis('plazo')}>Plazo de presentación</button>
            </div>
            <DensitySlider min={lo} max={hi} low={lo} high={hi}
              density={series.map((s) => s.count)}
              format={(i) => months[Math.round(i)] || ''}
              onChange={({ low, high }) => {
                const from = months[Math.round(low)], to = months[Math.round(high)]
                if (dateAxis === 'publication') patch({ pub_from: from ? `${from}-01` : '', pub_to: to ? `${to}-28` : '' })
                else patch({ deadline_from: from ? `${from}-01` : '', deadline_to: to ? `${to}-28` : '' })
              }} />
            <div className="presets">
              {['month', 'quarter', 'year', 'all'].map((p) => (
                <button key={p} className="preset" onClick={() => patch(presetRange(p))}>
                  {{ month: 'Último mes', quarter: '3 meses', year: 'Año', all: 'Todo' }[p]}
                </button>
              ))}
              <button className="preset" onClick={() => patch({ deadline_from: todayISO() })}>Plazo abierto</button>
            </div>
          </div>
        )
      }
      default: return null
    }
  }

  return (
    <div className="ws-overlay" role="dialog" aria-label="Filtros">
      <div className="ws-panel">
        <div className="ws-head"><span>Filtros</span>
          <button type="button" className="ws-close" aria-label="Cerrar" onClick={onClose}><X size={18} /></button></div>
        <div className="ws-body">
          <nav className="ws-cats">
            {CATS.map((c) => {
              const n = catCount(c, filters)
              return (
                <button key={c.id} type="button"
                  className={`ws-cat${active === c.id ? ' on' : ''}`} onClick={() => setActive(c.id)}>
                  <c.Icon size={18} /> <span>{c.label}</span>
                  {n > 0 && <span className="ws-badge">{n}</span>}
                </button>
              )
            })}
          </nav>
          <section className="ws-view">{center()}</section>
          <LiveResults total={total} results={previewResults} loading={loading} />
        </div>
        <div className="ws-foot">
          <span className="ws-foot-count">{total != null ? total.toLocaleString('es-ES') : '—'} resultados</span>
          <button type="button" className="ws-apply" onClick={onClose}>Ver resultados</button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add styles** to `styles.css`:

```css
.ws-overlay { position: fixed; inset: 0; background: rgba(22,26,35,.45); z-index: 50; display: flex; align-items: stretch; justify-content: center; padding: 28px; }
.ws-panel { background: var(--card); border-radius: 16px; box-shadow: var(--shadow); width: min(1100px, 100%); display: flex; flex-direction: column; overflow: hidden; }
.ws-head { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--line); font-weight: 700; }
.ws-close { background: none; border: none; color: var(--muted); }
.ws-body { display: flex; flex: 1; min-height: 0; }
.ws-cats { flex: 0 0 190px; border-right: 1px solid var(--line); padding: 10px; display: flex; flex-direction: column; gap: 4px; overflow: auto; }
.ws-cat { display: flex; align-items: center; gap: 9px; border: none; background: none; color: var(--ink); padding: 9px 11px; border-radius: 9px; font-size: 13.5px; font-weight: 600; text-align: left; }
.ws-cat span { flex: 1; }
.ws-cat:hover { background: var(--accent-soft); }
.ws-cat.on { background: var(--accent); color: #fff; }
.ws-badge { background: var(--accent-soft); color: var(--accent); border-radius: 999px; font-size: 11px; padding: 0 7px; min-width: 18px; text-align: center; }
.ws-cat.on .ws-badge { background: #fff; color: var(--accent); }
.ws-view { flex: 1; padding: 18px; overflow: auto; min-width: 0; }
.ws-body .live-results { flex: 0 0 200px; border-left: 1px solid var(--line); padding: 14px; }
.ws-foot { display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; border-top: 1px solid var(--line); }
.ws-foot-count { color: var(--ok); font-weight: 700; }
.ws-apply { background: var(--accent); color: #fff; border: none; border-radius: 9px; padding: 9px 18px; font-weight: 600; }
.ws-axis { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; margin-bottom: 8px; }
.ws-axis button { border: none; background: #fff; color: var(--muted); padding: 5px 14px; font-size: 12px; font-weight: 600; }
.ws-axis button.on { background: var(--ink); color: #fff; }
@media (max-width: 800px) { .ws-body { flex-direction: column; } .ws-cats { flex-direction: row; flex-wrap: wrap; flex-basis: auto; } .ws-body .live-results { border-left: none; border-top: 1px solid var(--line); } }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd search-ui && npx vitest run src/components/FilterWorkspace.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/components/FilterWorkspace.jsx search-ui/src/components/FilterWorkspace.test.jsx search-ui/src/styles.css
git commit -m "feat: FilterWorkspace three-zone overlay shell"
```

---

## Task 16: Frontend — `App` integration, `ActiveFilters` restyle, retire old components

**Files:**
- Modify: `search-ui/src/App.jsx`
- Modify: `search-ui/src/components/ActiveFilters.jsx`
- Modify: `search-ui/src/styles.css`
- Delete: `FilterRail.jsx`, `FilterDrawer.jsx`, `CpvSelect.jsx`, `NutsSelect.jsx`, `RangeSlider.jsx`, `BudgetRange.jsx`, `DateTimeline.jsx`
- Test: `search-ui/src/components/App.test.jsx` (create)

**Interfaces:**
- Consumes: `FilterWorkspace`, `facets` from `api.js`, `activeFilterList`, `filtersToParams`.
- `App` owns: `filtersOpen` state, `facetsData`/`total` from a debounced `facets()` call keyed on `filters`, and passes preview results (the current `state.data.results`) into the workspace.

- [ ] **Step 1: Write the failing test** (App renders header + Filtros button)

```javascript
// search-ui/src/components/App.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../App.jsx'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
    const body = String(url).includes('/api/facets')
      ? { total: 0, nuts: {}, dates: { publication: [], plazo: [] } }
      : { query: '', mode: 'browse', count: 0, total: 0, offset: 0, results: [], errors: null }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  })
  globalThis.crypto = globalThis.crypto || { randomUUID: () => 'x', getRandomValues: () => {} }
})

describe('App', () => {
  it('shows the Filtros button and opens the workspace', async () => {
    render(<App />)
    const open = await screen.findByRole('button', { name: /filtros/i })
    fireEvent.click(open)
    expect(await screen.findByRole('dialog', { name: /filtros/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd search-ui && npx vitest run src/components/App.test.jsx`
Expected: FAIL (no Filtros button yet)

- [ ] **Step 3: Rewrite `App.jsx`** — remove `FilterRail`/`FilterDrawer`/`TABS` drawer logic; add the Filtros button + workspace + facets fetch. Key changes:

Replace imports of the retired components with:

```jsx
import { search, facets, sendFeedback, removeFeedback } from './api.js'
import FilterWorkspace from './components/FilterWorkspace.jsx'
import { SlidersHorizontal, MagnifyingGlass } from './icons.js'
```

Remove `import FilterRail`, `FilterDrawer`, `CpvSelect`, `NutsSelect`, `MultiCheck`, `BudgetRange`, `DateTimeline`, and the `drawerContent`/`openTab`/`counts`/`TABS`/`openTabDef` machinery.

Add state and a debounced facets effect:

```jsx
const [filtersOpen, setFiltersOpen] = useState(false)
const [facetsData, setFacetsData] = useState({ nuts: {}, dates: { publication: [], plazo: [] } })
const [total, setTotal] = useState(null)

useEffect(() => {
  const params = filtersToParams(filters)
  const id = setTimeout(async () => {
    try {
      const f = await facets({ q: q.trim(), ...params })
      setFacetsData(f); setTotal(f.total)
    } catch { /* degrade silently — filtering still works */ }
  }, 250)
  return () => clearTimeout(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [filters, q])
```

In the JSX header, add the button after the form buttons:

```jsx
<button type="button" className="filtros-btn" onClick={() => setFiltersOpen(true)}>
  <SlidersHorizontal size={18} /> Filtros
  {activeFilterList(filters).length > 0 && <span className="filtros-badge">{activeFilterList(filters).length}</span>}
</button>
```

Replace the `<FilterRail/>` + `{openTabDef && <FilterDrawer.../>}` block at the end of `<main>` with:

```jsx
{filtersOpen && (
  <FilterWorkspace
    filters={filters} patch={patch} setList={setList}
    facetsData={facetsData} total={total}
    previewResults={state.status === 'done' ? state.data.results : []}
    loading={state.status === 'loading'}
    onClose={() => { setFiltersOpen(false); run(0) }}
  />
)}
```

Update the results layout: remove the `.layout` flex/rail wrapper so `.results` is the single column (keep `ActiveFilters`, meta, cards, "Cargar más"). Change the "Cargar más" condition from `state.data.count === K` to use the real total:

```jsx
{(state.data.offset || 0) + state.data.results.length < (state.data.total ?? 0) && (
  <button className="more" onClick={() => run((state.data.offset || 0) + K)}>Cargar más</button>
)}
```

- [ ] **Step 4: Restyle header form + Filtros button** in `styles.css`:

```css
.filtros-btn { display: inline-flex; align-items: center; gap: 7px; background: #fff; color: var(--accent); border: 1px solid var(--line); }
.filtros-btn:hover { border-color: var(--accent); }
.filtros-badge { background: var(--accent); color: #fff; border-radius: 999px; font-size: 11px; padding: 0 6px; }
.layout { display: block; }
```

- [ ] **Step 5: Light restyle of `ActiveFilters.jsx`** — verify it still renders chips with the existing `.chip`/`.active-filters` classes (no structural change needed; confirm by reading the file). If it imports nothing retired, leave logic intact.

- [ ] **Step 6: Delete retired components**

```bash
cd search-ui && git rm src/components/FilterRail.jsx src/components/FilterDrawer.jsx \
  src/components/CpvSelect.jsx src/components/NutsSelect.jsx \
  src/components/RangeSlider.jsx src/components/BudgetRange.jsx src/components/DateTimeline.jsx
```

Also delete any now-orphaned tests for them (e.g. `cpv.test.js` only if it tested `CpvSelect`; keep `cpv.js` helper tests). Verify nothing imports the deleted files:

Run: `cd search-ui && grep -rn "FilterRail\|FilterDrawer\|CpvSelect\|NutsSelect\|RangeSlider\|BudgetRange\|DateTimeline" src` 
Expected: no matches.

- [ ] **Step 7: Run the full test suite + build**

Run: `cd search-ui && npx vitest run && npm run build`
Expected: all tests PASS, build succeeds.

- [ ] **Step 8: Commit**

```bash
git add -A search-ui/src
git commit -m "feat: integrate FilterWorkspace into App, retire rail/drawer components"
```

---

## Task 17: Backend deps + final integration verification

**Files:**
- Modify: `search-api/requirements.txt` (only if a new import needs it — `facets.py` uses stdlib + `filters`, so likely no change; verify).
- Verify the full stack.

- [ ] **Step 1: Confirm backend tests pass**

Run: `cd search-api && python -m pytest -v`
Expected: all PASS (filters, facets, feedback).

- [ ] **Step 2: Confirm no new backend dependency is required**

Run: `cd search-api && python -c "import facets, filters, search_api"`
Expected: imports succeed with the existing `requirements.txt`. If `search_api` import fails for a missing package, add it to `requirements.txt` and re-run.

- [ ] **Step 3: Manual smoke (documented, not automated)**

With the stack running (`docker-compose up` per repo norms), verify in a browser:
- Header shows the `Filtros` button; clicking opens the overlay.
- CPV Miller columns drill; search jumps; chips add/remove.
- Ubicación map shades by density, toggles Comunidades/Provincias, click selects.
- Fechas density slider shows the subtle area; Publicación/Plazo switch works; presets apply.
- Presupuesto slider is log-scaled.
- Live count + preview update as filters change.
- Result cards show the right-side colored relevance gutter; toggling still posts feedback.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "chore: final integration fixes for UI redesign"
```

---

## Self-Review Notes (for the implementer)

- The **date-bucketing fallback** (spec risk): if `/api/facets` month aggregation is too slow in practice, Task 15's `dates` view still works without the density area (pass `density={[]}`), and Task 3's per-month aggregation can be capped lower than 36. The slider remains functional.
- **CPV `value` shape** is unchanged from the old `CpvSelect` (array of codes), so `filters.cpv` and `filtersToParams` need no change.
- **NUTS selection across levels**: selecting a community code filters its provinces too, because the backend uses `Like "ES30*"`. This is intended.
- If `@phosphor-icons/react` icon names differ across versions, adjust `icons.js` imports (e.g. `CurrencyEur` vs `CurrencyEur`); the icon set is stable but verify on install.
