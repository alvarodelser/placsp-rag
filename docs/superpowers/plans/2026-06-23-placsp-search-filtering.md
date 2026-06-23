# PLACSP Search Structured Filtering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured filters (dates, CPV, status/result, type, procedure, NUTS, budget) and a no-query browse mode to the PLACSP search stack, with a human-readable hierarchical CPV picker in the UI.

**Architecture:** All filter→Weaviate translation lives in a pure, stdlib-only module (`search-api/filters.py`) consumed by the FastAPI endpoint, so it is unit-testable with no FastAPI/Weaviate dependency. Code→label decoding is shipped as static JSON generated from the `.gc` codelists and bundled into the React app; the API only ever handles raw codes. CPV hierarchy (browse, breadcrumbs, prefix selection) is derived client-side from the flat CPV map and matched server-side with a prefix `Like`.

**Tech Stack:** Python 3.11 (FastAPI, httpx, lxml), Weaviate GraphQL, React 18 + Vite, Vitest.

## Global Constraints

- Python `requires-python >=3.11`.
- `search-api` runtime deps are **only** `fastapi`, `uvicorn[standard]`, `httpx` — `filters.py` MUST be **stdlib-only** (no third-party imports). Do not add API dependencies.
- The API handles **raw codes only**; never load or serve labels server-side.
- Codelist JSON is **generated from `codelists/*.gc` and committed** to the repo.
- All active filters combine with **AND**; values within one repeatable filter combine with **OR**.
- `cpv` and `nuts` match by **prefix** (`Like "<code>*"`); `status`/`result`/`contract_type`/`procedure` match **exact** (`Equal`).
- Browse mode `sort` is restricted to an **allowlist** of fields; default `publication_date desc`.
- UI copy is **Spanish**, matching existing components.
- Weaviate class name comes from env `PLACSP_CLASS` (default `Placsp_licitaciones`); date filter values are RFC3339.

---

## File Structure

- `scripts/build_codelists_json.py` (new) — converts six `.gc` files to JSON maps under `search-ui/src/codelists/`.
- `search-ui/src/codelists/*.json` (new, generated+committed) — `cpv`, `status`, `result`, `contract_type`, `procedure`, `nuts`.
- `search-api/filters.py` (new) — pure filter logic: `build_where`, `where_to_gql`, `build_sort`, `sort_to_gql`.
- `search-api/search_api.py` (modify) — optional `q`, new filter params, `offset`, browse path, wire `filters.py`.
- `search-api/test_filters.py` (new) — unit tests for `filters.py`.
- `tests/test_build_codelists.py` (new) — tests the build script against a fixture.
- `pyproject.toml` (modify) — add `search-api` and `scripts` to pytest `pythonpath`.
- `src/placsp/weaviate_schema.py` (modify, **conditional** Task 4) — `tokenization:"field"` for `cpv`/`nuts`.
- `search-ui/src/cpv.js` (new) — `cpvLevel`, `cpvPath`.
- `search-ui/src/cpv.test.js` (new) — helper tests.
- `search-ui/src/api.js` (modify) — `buildQuery`, filter-aware `search`.
- `search-ui/src/api.test.js` (new) — `buildQuery` tests.
- `search-ui/src/components/CpvSelect.jsx` (new) — CPV typeahead + chips.
- `search-ui/src/components/FilterPanel.jsx` (new) — status/result/type/procedure/date/budget/sort controls.
- `search-ui/src/App.jsx` (modify) — filter state, browse mode, pagination, active chips.
- `search-ui/src/components/ResultCard.jsx` (modify) — show CPV labels.
- `search-ui/src/styles.css` (modify) — styles for filter panel/chips.
- `search-ui/package.json` (modify) — add `vitest`, `test` script.

---

## Task 1: Codelist → JSON build script

**Files:**
- Create: `scripts/build_codelists_json.py`
- Test: `tests/test_build_codelists.py`
- Modify: `pyproject.toml` (pytest `pythonpath`)

**Interfaces:**
- Consumes: `placsp.codelists.parse_gc(path) -> dict[str,str]` (existing).
- Produces: `gc_to_json_map(path: str) -> dict[str,str]`; `main(argv: list[str] | None = None) -> None`; module constant `MAPPING: dict[str,str]` of `{out_name: gc_filename}`.

- [ ] **Step 1: Add search-api and scripts to pytest path**

Modify `pyproject.toml`, replacing the `pythonpath` line:

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "search-api", "scripts"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_build_codelists.py`:

```python
import json
import build_codelists_json as b


def test_gc_to_json_map_reads_fixture():
    m = b.gc_to_json_map("tests/fixtures/ContractCode.gc")
    assert m["1"] == "Suministros"
    assert len(m) >= 3


def test_main_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "MAPPING", {"contract_type": "ContractCode.gc"})
    b.main(["--codelists-dir", "tests/fixtures", "--out-dir", str(tmp_path)])
    out = json.loads((tmp_path / "contract_type.json").read_text(encoding="utf-8"))
    assert out["1"] == "Suministros"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_build_codelists.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_codelists_json'`.

- [ ] **Step 4: Write the script**

Create `scripts/build_codelists_json.py`:

```python
"""Generate static codelist JSON maps for the search UI.

Parses the CODICE .gc codelists into flat {code: spanish_label} JSON files,
committed under search-ui/src/codelists/ and bundled by Vite. The search API
never sees labels; only the UI uses these to decode/search codes.

Usage:
  python scripts/build_codelists_json.py
  python scripts/build_codelists_json.py --codelists-dir codelists --out-dir search-ui/src/codelists
"""
import argparse
import json
import os

from placsp.codelists import parse_gc

# out_name -> .gc filename in the codelists dir
MAPPING = {
    "cpv": "CPV2008-2.04.gc",
    "status": "SyndicationContractFolderStatusCode-2.04.gc",
    "result": "TenderResultCode-2.09.gc",
    "contract_type": "ContractCode-2.08.gc",
    "procedure": "SyndicationTenderingProcessCode-2.07.gc",
    "nuts": "NUTS-2021.gc",
}


def gc_to_json_map(path: str) -> dict[str, str]:
    return parse_gc(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codelists-dir", default="codelists")
    ap.add_argument("--out-dir", default="search-ui/src/codelists")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    for out_name, gc_file in MAPPING.items():
        src = os.path.join(args.codelists_dir, gc_file)
        m = gc_to_json_map(src)
        dst = os.path.join(args.out_dir, f"{out_name}.json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, sort_keys=True)
        print(f"{out_name}: {len(m)} codes -> {dst}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_build_codelists.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Generate the real codelist JSON and sanity-check counts**

Run: `python scripts/build_codelists_json.py`
Expected: prints six lines; `cpv` ~18,900 codes; `status`, `result`, `contract_type`, `procedure`, `nuts` each > 0. **If any list prints `0 codes`, parse_gc's column handling does not match that `.gc` file's `ColumnRef` names — inspect the file and adjust `parse_gc` before proceeding.**

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml scripts/build_codelists_json.py tests/test_build_codelists.py search-ui/src/codelists
git commit -m "feat: generate static codelist JSON for the search UI"
```

---

## Task 2: API filter logic (pure module)

**Files:**
- Create: `search-api/filters.py`
- Test: `search-api/test_filters.py`

**Interfaces:**
- Produces:
  - `build_where(*, cpv=None, status=None, result=None, contract_type=None, procedure=None, nuts=None, pub_from=None, pub_to=None, deadline_from=None, deadline_to=None, budget_min=None, budget_max=None) -> dict | None`
  - `where_to_gql(where: dict) -> str`
  - `build_sort(sort: str | None) -> list[dict]`
  - `sort_to_gql(sort: list[dict]) -> str`
  - `SORT_FIELDS: set[str]`
- Consumed by: Task 3 (`search_api.py`).

- [ ] **Step 1: Write the failing tests**

Create `search-api/test_filters.py`:

```python
import filters as f


def test_build_where_none_when_empty():
    assert f.build_where() is None


def test_build_where_single_cpv_prefix():
    w = f.build_where(cpv=["45"])
    assert w == {"path": ["cpv"], "operator": "Like", "valueText": "45*"}


def test_build_where_multi_cpv_is_or():
    w = f.build_where(cpv=["45", "72"])
    assert w["operator"] == "Or"
    assert {"path": ["cpv"], "operator": "Like", "valueText": "45*"} in w["operands"]
    assert {"path": ["cpv"], "operator": "Like", "valueText": "72*"} in w["operands"]


def test_build_where_status_exact():
    w = f.build_where(status=["PUB"])
    assert w == {"path": ["status_code"], "operator": "Equal", "valueText": "PUB"}


def test_build_where_date_range_rfc3339():
    w = f.build_where(pub_from="2026-01-01", pub_to="2026-01-31")
    paths = [o for o in w["operands"]]
    assert w["operator"] == "And"
    assert {"path": ["publication_date"], "operator": "GreaterThanEqual",
            "valueDate": "2026-01-01T00:00:00Z"} in paths
    assert {"path": ["publication_date"], "operator": "LessThanEqual",
            "valueDate": "2026-01-31T23:59:59Z"} in paths


def test_build_where_budget_range():
    w = f.build_where(budget_min=1000, budget_max=5000)
    assert {"path": ["budget_amount"], "operator": "GreaterThanEqual",
            "valueNumber": 1000.0} in w["operands"]


def test_build_where_combines_with_and():
    w = f.build_where(cpv=["45"], status=["PUB"])
    assert w["operator"] == "And"
    assert len(w["operands"]) == 2


def test_where_to_gql_leaf():
    s = f.where_to_gql({"path": ["cpv"], "operator": "Like", "valueText": "45*"})
    assert s == 'where: { path: ["cpv"], operator: Like, valueText: "45*" }'


def test_where_to_gql_nested_enums_unquoted():
    w = {"operator": "And", "operands": [
        {"path": ["cpv"], "operator": "Like", "valueText": "45*"},
        {"path": ["status_code"], "operator": "Equal", "valueText": "PUB"},
    ]}
    s = f.where_to_gql(w)
    assert "operator: And" in s
    assert "operator: Like" in s
    assert '"And"' not in s  # operator enum must not be quoted


def test_build_sort_default_and_allowlist():
    assert f.build_sort(None) == [{"path": ["publication_date"], "order": "desc"}]
    assert f.build_sort("budget_amount asc") == [{"path": ["budget_amount"], "order": "asc"}]
    # unknown field falls back to default
    assert f.build_sort("DROP TABLE desc") == [{"path": ["publication_date"], "order": "desc"}]


def test_sort_to_gql():
    s = f.sort_to_gql([{"path": ["publication_date"], "order": "desc"}])
    assert s == 'sort: [{ path: ["publication_date"], order: desc }]'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest search-api/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'filters'`.

- [ ] **Step 3: Write the implementation**

Create `search-api/filters.py`:

```python
"""Pure filter logic for the PLACSP search API (stdlib only, no FastAPI/httpx).

Translates structured filter params into Weaviate `where` / `sort` objects and
serializes them to GraphQL argument strings. Kept dependency-free so it is
unit-testable without a running Weaviate.
"""
import json

SORT_FIELDS = {
    "publication_date", "submission_deadline", "award_date",
    "budget_amount", "estimated_value",
}
_DEFAULT_SORT = [{"path": ["publication_date"], "order": "desc"}]


def _or(operands: list[dict]) -> dict:
    return operands[0] if len(operands) == 1 else {"operator": "Or", "operands": operands}


def _prefix(prop: str, values: list[str]) -> dict:
    return _or([{"path": [prop], "operator": "Like", "valueText": f"{v}*"} for v in values])


def _equal(prop: str, values: list[str]) -> dict:
    return _or([{"path": [prop], "operator": "Equal", "valueText": v} for v in values])


def _date(prop: str, value: str, op: str, end_of_day: bool) -> dict:
    suffix = "T23:59:59Z" if end_of_day else "T00:00:00Z"
    return {"path": [prop], "operator": op, "valueDate": f"{value}{suffix}"}


def _number(prop: str, value: float, op: str) -> dict:
    return {"path": [prop], "operator": op, "valueNumber": float(value)}


def build_where(*, cpv=None, status=None, result=None, contract_type=None,
                procedure=None, nuts=None, pub_from=None, pub_to=None,
                deadline_from=None, deadline_to=None,
                budget_min=None, budget_max=None) -> dict | None:
    ops: list[dict] = []
    if cpv:
        ops.append(_prefix("cpv", cpv))
    if nuts:
        ops.append(_prefix("nuts", nuts))
    if status:
        ops.append(_equal("status_code", status))
    if result:
        ops.append(_equal("result_code", result))
    if contract_type:
        ops.append(_equal("contract_type_code", contract_type))
    if procedure:
        ops.append(_equal("procedure_code", procedure))
    if pub_from:
        ops.append(_date("publication_date", pub_from, "GreaterThanEqual", False))
    if pub_to:
        ops.append(_date("publication_date", pub_to, "LessThanEqual", True))
    if deadline_from:
        ops.append(_date("submission_deadline", deadline_from, "GreaterThanEqual", False))
    if deadline_to:
        ops.append(_date("submission_deadline", deadline_to, "LessThanEqual", True))
    if budget_min is not None:
        ops.append(_number("budget_amount", budget_min, "GreaterThanEqual"))
    if budget_max is not None:
        ops.append(_number("budget_amount", budget_max, "LessThanEqual"))
    if not ops:
        return None
    return ops[0] if len(ops) == 1 else {"operator": "And", "operands": ops}


def _node_to_gql(node: dict) -> str:
    if "operands" in node:
        inner = ", ".join(_node_to_gql(o) for o in node["operands"])
        return f"{{ operator: {node['operator']}, operands: [{inner}] }}"
    path = json.dumps(node["path"])  # ["cpv"] with double quotes -> valid GraphQL
    parts = [f"path: {path}", f"operator: {node['operator']}"]
    if "valueText" in node:
        parts.append(f"valueText: {json.dumps(node['valueText'])}")
    elif "valueDate" in node:
        parts.append(f"valueDate: {json.dumps(node['valueDate'])}")
    elif "valueNumber" in node:
        parts.append(f"valueNumber: {node['valueNumber']}")
    return "{ " + ", ".join(parts) + " }"


def where_to_gql(where: dict) -> str:
    return f"where: {_node_to_gql(where)}"


def build_sort(sort: str | None) -> list[dict]:
    if not sort:
        return list(_DEFAULT_SORT)
    parts = sort.split()
    field = parts[0] if parts else ""
    order = parts[1].lower() if len(parts) > 1 else "desc"
    if field not in SORT_FIELDS or order not in ("asc", "desc"):
        return list(_DEFAULT_SORT)
    return [{"path": [field], "order": order}]


def sort_to_gql(sort: list[dict]) -> str:
    items = ", ".join(
        f'{{ path: {json.dumps(s["path"])}, order: {s["order"]} }}' for s in sort
    )
    return f"sort: [{items}]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest search-api/test_filters.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add search-api/filters.py search-api/test_filters.py
git commit -m "feat: pure Weaviate filter/sort builder for search API"
```

---

## Task 3: Wire filters into the search endpoint

**Files:**
- Modify: `search-api/search_api.py`

**Interfaces:**
- Consumes: `filters.build_where`, `filters.where_to_gql`, `filters.build_sort`, `filters.sort_to_gql` (Task 2).
- Produces: extended `GET /api/search` accepting `q` (optional) plus all filter params, `sort`, `offset`.

- [ ] **Step 1: Add the import**

In `search-api/search_api.py`, after the existing imports (around line 19), add:

```python
import filters as filt
```

- [ ] **Step 2: Replace the `search` handler signature and body**

Replace the entire `search` function (currently `search-api/search_api.py:57-96`) with:

```python
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
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `cd search-api && python -c "import search_api; print('ok')"`
Expected: prints `ok` (requires `fastapi`, `httpx` installed; if not, run `pip install -r search-api/requirements.txt` first).

- [ ] **Step 4: Verify CPV/NUTS prefix matching against live Weaviate (manual)**

Start the API (`uvicorn search_api:app --port 8092` from `search-api/`, with the deployment env) and run:

Run: `curl -s "http://localhost:8092/api/search?cpv=45&k=3" | python -m json.tool`
Expected: `mode: "browse"`, up to 3 results, each with at least one `cpv` value starting `45`, sorted by `publication_date` desc. **If results are empty but unfiltered browse returns data, prefix `Like` is not matching the `cpv` tokenization → do Task 4, then re-test.**

- [ ] **Step 5: Commit**

```bash
git add search-api/search_api.py
git commit -m "feat: structured filters, browse mode, and pagination on /api/search"
```

---

## Task 4: (CONDITIONAL) CPV/NUTS tokenization fallback

**Run this task ONLY if Task 3 Step 4 showed prefix matching failing.** Re-indexing is required after this change; coordinate with the ingestion run.

**Files:**
- Modify: `src/placsp/weaviate_schema.py`
- Test: `tests/test_weaviate_schema.py`

**Interfaces:**
- Produces: `cpv` and `nuts` properties defined with `tokenization: "field"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_weaviate_schema.py`:

```python
from placsp.weaviate_schema import CLASS_DEF


def test_cpv_and_nuts_use_field_tokenization():
    props = {p["name"]: p for p in CLASS_DEF["properties"]}
    assert props["cpv"].get("tokenization") == "field"
    assert props["nuts"].get("tokenization") == "field"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_weaviate_schema.py::test_cpv_and_nuts_use_field_tokenization -v`
Expected: FAIL (tokenization not set).

- [ ] **Step 3: Update the schema builder**

In `src/placsp/weaviate_schema.py`, change the `cpv` array property and the `nuts` text property so each includes `"tokenization": "field"`. For `cpv`, replace the array line (`src/placsp/weaviate_schema.py:14`) so `cpv` is built separately:

```python
    out += [{"name": "document_urls", "dataType": ["text[]"]}]
    out += [{"name": "cpv", "dataType": ["text[]"], "tokenization": "field"}]
```

And for `nuts`, remove it from the bulk `text(n)` list (line 7-13) and append explicitly:

```python
    out += [{"name": "nuts", "dataType": ["text"], "tokenization": "field"}]
```

(Remove the string `"nuts"` from the list comprehension so it is not defined twice.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_weaviate_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Recreate the class and re-index, then re-run Task 3 Step 4**

Re-run ingestion per `docs/RUNBOOK.md` to recreate the class with the new tokenization, then repeat Task 3 Step 4's curl check. Expected: CPV prefix filter now returns matching results.

- [ ] **Step 6: Commit**

```bash
git add src/placsp/weaviate_schema.py tests/test_weaviate_schema.py
git commit -m "fix: field tokenization for cpv/nuts to enable prefix filtering"
```

---

## Task 5: UI — CPV hierarchy helpers + Vitest

**Files:**
- Modify: `search-ui/package.json`
- Create: `search-ui/src/cpv.js`
- Create: `search-ui/src/cpv.test.js`

**Interfaces:**
- Produces: `cpvLevel(code: string) -> number` (significant digit length, 2–8); `cpvPath(code: string, cpvMap: Record<string,string>) -> string[]` (ancestor labels, division→…, excluding the code itself).
- Consumed by: Task 7 (`CpvSelect`), Task 9 (`ResultCard`).

- [ ] **Step 1: Add Vitest to package.json**

In `search-ui/package.json`, add a `test` script and devDependency:

```json
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview --port 4173",
    "test": "vitest run"
  },
```

and under `devDependencies` add:

```json
    "vitest": "^2.1.0"
```

- [ ] **Step 2: Install**

Run: `cd search-ui && npm install`
Expected: installs vitest without error.

- [ ] **Step 3: Write the failing tests**

Create `search-ui/src/cpv.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { cpvLevel, cpvPath } from './cpv.js'

const MAP = {
  '45000000': 'Construcción',
  '45200000': 'Construcción completa',
  '45210000': 'Edificios',
  '45211000': 'Viviendas',
}

describe('cpvLevel', () => {
  it('returns significant digit length', () => {
    expect(cpvLevel('45000000')).toBe(2)
    expect(cpvLevel('45200000')).toBe(3)
    expect(cpvLevel('45210000')).toBe(4)
    expect(cpvLevel('45211000')).toBe(5)
  })
  it('strips a check-digit suffix', () => {
    expect(cpvLevel('45211000-1')).toBe(5)
  })
})

describe('cpvPath', () => {
  it('lists ancestor labels from division down, excluding self', () => {
    expect(cpvPath('45211000', MAP)).toEqual(['Construcción', 'Construcción completa', 'Edificios'])
  })
  it('returns empty for a division', () => {
    expect(cpvPath('45000000', MAP)).toEqual([])
  })
})
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd search-ui && npm test`
Expected: FAIL — cannot resolve `./cpv.js`.

- [ ] **Step 5: Write the helpers**

Create `search-ui/src/cpv.js`:

```js
// CPV hierarchy is encoded in the 8 digits: division(2) > group(3) > class(4)
// > category(5) > detail(6-8). We derive level and ancestor path from the code
// itself plus the flat {code: label} map, so no extra data structure is needed.

function normalize(code) {
  return String(code).split('-')[0].padEnd(8, '0').slice(0, 8)
}

export function cpvLevel(code) {
  const d = normalize(code).replace(/0+$/, '')
  return Math.max(d.length, 2)
}

export function cpvPath(code, cpvMap) {
  const d = normalize(code)
  const sig = cpvLevel(code)
  const labels = []
  for (let len = 2; len < sig; len++) {
    const ancestor = d.slice(0, len).padEnd(8, '0')
    if (ancestor !== d && cpvMap[ancestor]) labels.push(cpvMap[ancestor])
  }
  return labels
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd search-ui && npm test`
Expected: PASS (cpvLevel + cpvPath suites).

- [ ] **Step 7: Commit**

```bash
git add search-ui/package.json search-ui/package-lock.json search-ui/src/cpv.js search-ui/src/cpv.test.js
git commit -m "feat: CPV hierarchy helpers + vitest in search UI"
```

---

## Task 6: UI — filter-aware API client

**Files:**
- Modify: `search-ui/src/api.js`
- Create: `search-ui/src/api.test.js`

**Interfaces:**
- Produces: `buildQuery(params: object) -> string` (query string without leading `?`, omitting empty values, repeating array params); `search(params: object) -> Promise<object>`.
- Consumed by: Task 9 (`App.jsx`).

- [ ] **Step 1: Write the failing tests**

Create `search-ui/src/api.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { buildQuery } from './api.js'

describe('buildQuery', () => {
  it('omits empty values', () => {
    expect(buildQuery({ q: 'obras', mode: 'hybrid', cpv: [], status: '' }))
      .toBe('q=obras&mode=hybrid')
  })
  it('repeats array params', () => {
    expect(buildQuery({ cpv: ['45', '72'] })).toBe('cpv=45&cpv=72')
  })
  it('encodes values', () => {
    expect(buildQuery({ q: 'obras públicas' })).toBe('q=obras%20p%C3%BAblicas')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search-ui && npm test`
Expected: FAIL — `buildQuery` is not exported.

- [ ] **Step 3: Rewrite api.js**

Replace the contents of `search-ui/src/api.js` with:

```js
const BASE = (import.meta.env.VITE_API_BASE || '/placsprag').replace(/\/$/, '')

export function buildQuery(params) {
  const parts = []
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      for (const v of value) {
        if (v == null || v === '') continue
        parts.push(`${key}=${encodeURIComponent(v)}`)
      }
    } else {
      parts.push(`${key}=${encodeURIComponent(value)}`)
    }
  }
  return parts.join('&')
}

export async function search(params) {
  const url = `${BASE}/api/search?${buildQuery(params)}`
  const r = await fetch(url)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search-ui && npm test`
Expected: PASS (buildQuery suite).

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/api.js search-ui/src/api.test.js
git commit -m "feat: filter-aware search API client with buildQuery"
```

---

## Task 7: UI — CPV typeahead selector

**Files:**
- Create: `search-ui/src/components/CpvSelect.jsx`

**Interfaces:**
- Consumes: `cpvLevel`, `cpvPath` (Task 5); `search-ui/src/codelists/cpv.json` (Task 1).
- Produces: `<CpvSelect value={string[]} onChange={(string[]) => void} />` — `value` is the list of selected CPV codes.

- [ ] **Step 1: Build the component**

Create `search-ui/src/components/CpvSelect.jsx`:

```jsx
import { useMemo, useState } from 'react'
import cpvMap from '../codelists/cpv.json'
import { cpvLevel, cpvPath } from '../cpv.js'

const ENTRIES = Object.entries(cpvMap) // [code, label][]

export default function CpvSelect({ value, onChange }) {
  const [term, setTerm] = useState('')

  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.startsWith(t) || label.toLowerCase().includes(t)) {
        out.push([code, label])
        if (out.length >= 50) break
      }
    }
    return out
  }, [term])

  function add(code) {
    if (!value.includes(code)) onChange([...value, code])
    setTerm('')
  }
  function remove(code) {
    onChange(value.filter((c) => c !== code))
  }

  return (
    <div className="cpv-select">
      <input
        type="search"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="CPV: código o descripción (p. ej. limpieza)"
      />
      {matches.length > 0 && (
        <ul className="cpv-suggestions">
          {matches.map(([code, label]) => (
            <li key={code} onClick={() => add(code)}>
              <span className="cpv-code">{code}</span> · {label}
              {cpvPath(code, cpvMap).length > 0 && (
                <div className="cpv-path">{cpvPath(code, cpvMap).join(' › ')}</div>
              )}
            </li>
          ))}
        </ul>
      )}
      {value.length > 0 && (
        <div className="chips">
          {value.map((code) => (
            <span className="chip" key={code}>
              {code} · {cpvMap[code] || '—'}
              {cpvLevel(code) < 8 && <em className="hint"> (incluye sub-códigos)</em>}
              <button type="button" onClick={() => remove(code)} aria-label="Quitar">✕</button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds (component is not yet mounted; this confirms imports/JSON resolve).

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/CpvSelect.jsx
git commit -m "feat: CPV typeahead selector with breadcrumb paths"
```

---

## Task 8: UI — filter panel (status/result/type/procedure/date/budget/sort)

**Files:**
- Create: `search-ui/src/components/FilterPanel.jsx`

**Interfaces:**
- Consumes: codelist JSONs (Task 1); `<CpvSelect>` (Task 7).
- Produces: `<FilterPanel filters={object} onChange={(object) => void} browse={boolean} />`. The `filters` object shape: `{ cpv:[], status:[], result:[], contract_type:[], procedure:[], nuts:[], pub_from:'', pub_to:'', deadline_from:'', deadline_to:'', budget_min:'', budget_max:'', sort:'' }`.

- [ ] **Step 1: Build the component**

Create `search-ui/src/components/FilterPanel.jsx`:

```jsx
import statusMap from '../codelists/status.json'
import resultMap from '../codelists/result.json'
import typeMap from '../codelists/contract_type.json'
import procMap from '../codelists/procedure.json'
import CpvSelect from './CpvSelect.jsx'

const SORTS = [
  ['publication_date desc', 'Publicación (recientes)'],
  ['submission_deadline asc', 'Plazo (próximos)'],
  ['budget_amount desc', 'Presupuesto (mayor)'],
]

function MultiCheck({ label, map, value, onChange }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }
  return (
    <fieldset className="filter-group">
      <legend>{label}</legend>
      <div className="checks">
        {Object.entries(map).map(([code, name]) => (
          <label key={code} className="check">
            <input type="checkbox" checked={value.includes(code)} onChange={() => toggle(code)} />
            {name}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export default function FilterPanel({ filters, onChange, browse }) {
  const set = (patch) => onChange({ ...filters, ...patch })

  return (
    <aside className="filter-panel">
      <fieldset className="filter-group">
        <legend>CPV</legend>
        <CpvSelect value={filters.cpv} onChange={(cpv) => set({ cpv })} />
      </fieldset>

      <MultiCheck label="Estado" map={statusMap} value={filters.status} onChange={(status) => set({ status })} />
      <MultiCheck label="Resultado" map={resultMap} value={filters.result} onChange={(result) => set({ result })} />
      <MultiCheck label="Tipo de contrato" map={typeMap} value={filters.contract_type} onChange={(contract_type) => set({ contract_type })} />
      <MultiCheck label="Procedimiento" map={procMap} value={filters.procedure} onChange={(procedure) => set({ procedure })} />

      <fieldset className="filter-group">
        <legend>Fecha de publicación</legend>
        <input type="date" value={filters.pub_from} onChange={(e) => set({ pub_from: e.target.value })} />
        <input type="date" value={filters.pub_to} onChange={(e) => set({ pub_to: e.target.value })} />
      </fieldset>

      <fieldset className="filter-group">
        <legend>Plazo de presentación</legend>
        <input type="date" value={filters.deadline_from} onChange={(e) => set({ deadline_from: e.target.value })} />
        <input type="date" value={filters.deadline_to} onChange={(e) => set({ deadline_to: e.target.value })} />
      </fieldset>

      <fieldset className="filter-group">
        <legend>Presupuesto (€)</legend>
        <input type="number" min="0" placeholder="mín" value={filters.budget_min} onChange={(e) => set({ budget_min: e.target.value })} />
        <input type="number" min="0" placeholder="máx" value={filters.budget_max} onChange={(e) => set({ budget_max: e.target.value })} />
      </fieldset>

      {browse && (
        <fieldset className="filter-group">
          <legend>Ordenar por</legend>
          <select value={filters.sort || 'publication_date desc'} onChange={(e) => set({ sort: e.target.value })}>
            {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </fieldset>
      )}
    </aside>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/FilterPanel.jsx
git commit -m "feat: filter panel for status/result/type/procedure/date/budget/sort"
```

---

## Task 9: UI — wire filters into App + show CPV labels in results

**Files:**
- Modify: `search-ui/src/App.jsx`
- Modify: `search-ui/src/components/ResultCard.jsx`
- Modify: `search-ui/src/styles.css`

**Interfaces:**
- Consumes: `search` (Task 6), `<FilterPanel>` (Task 8), `cpv.json` (Task 1).

- [ ] **Step 1: Rewrite App.jsx**

Replace the contents of `search-ui/src/App.jsx` with:

```jsx
import { useState } from 'react'
import { search } from './api.js'
import FilterPanel from './components/FilterPanel.jsx'
import ResultCard from './components/ResultCard.jsx'

const MODES = [
  ['hybrid', 'Híbrida'],
  ['vector', 'Semántica'],
  ['keyword', 'Palabra clave'],
]

const EMPTY = {
  cpv: [], status: [], result: [], contract_type: [], procedure: [], nuts: [],
  pub_from: '', pub_to: '', deadline_from: '', deadline_to: '',
  budget_min: '', budget_max: '', sort: '',
}

const K = 15

export default function App() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [filters, setFilters] = useState(EMPTY)
  const [state, setState] = useState({ status: 'idle' }) // idle | loading | done | error

  const browse = q.trim() === ''
  const hasFilters = Object.values(filters).some((v) => (Array.isArray(v) ? v.length : v))

  async function run(offset = 0) {
    if (browse && !hasFilters) return
    setState({ status: 'loading' })
    try {
      const data = await search({ q: q.trim(), mode, k: K, offset, ...filters })
      setState({ status: 'done', data })
    } catch (err) {
      setState({ status: 'error', message: err.message })
    }
  }

  function onSubmit(e) {
    e.preventDefault()
    run(0)
  }

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda semántica, por palabra clave y por filtros</div>
          <form onSubmit={onSubmit}>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza (o deja vacío y filtra)"
              autoFocus
            />
            <select value={mode} onChange={(e) => setMode(e.target.value)} title="Modo de búsqueda" disabled={browse}>
              {MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : browse ? 'Filtrar' : 'Buscar'}
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap layout">
          <FilterPanel filters={filters} onChange={setFilters} browse={browse} />

          <section className="results">
            {state.status === 'error' && <div className="err">Error: {state.message}</div>}

            {state.status === 'done' && (
              <>
                <div className="meta">{state.data.count} resultado(s) · modo {state.data.mode}</div>
                {state.data.errors && (
                  <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>
                )}
                {state.data.results.length > 0 ? (
                  <>
                    {state.data.results.map((r) => <ResultCard key={r._id || r.syndication_id} r={r} />)}
                    {state.data.count === K && (
                      <button className="more" onClick={() => run((state.data.offset || 0) + K)}>
                        Cargar más
                      </button>
                    )}
                  </>
                ) : (
                  <div className="empty">Sin resultados.</div>
                )}
              </>
            )}

            {state.status === 'idle' && (
              <div className="empty">Escribe una consulta o aplica filtros y pulsa Buscar.</div>
            )}
          </section>
        </div>
      </main>
    </>
  )
}
```

- [ ] **Step 2: Show CPV labels in ResultCard**

In `search-ui/src/components/ResultCard.jsx`, add the import at the top:

```jsx
import { money } from '../format.js'
import cpvMap from '../codelists/cpv.json'
```

and replace the CPV chips block (`search-ui/src/components/ResultCard.jsx:50-54`) with:

```jsx
      {Array.isArray(r.cpv) && r.cpv.length > 0 && (
        <div className="chips">
          {r.cpv.slice(0, 8).map((c) => (
            <span className="chip" key={c} title={cpvMap[c] || ''}>
              {c}{cpvMap[c] ? ` · ${cpvMap[c]}` : ''}
            </span>
          ))}
        </div>
      )}
```

- [ ] **Step 3: Add styles**

Append to `search-ui/src/styles.css`:

```css
.layout { display: flex; gap: 24px; align-items: flex-start; }
.filter-panel { flex: 0 0 280px; display: flex; flex-direction: column; gap: 14px; }
.results { flex: 1 1 auto; min-width: 0; }
.filter-group { border: 1px solid #ddd; border-radius: 8px; padding: 10px; }
.filter-group legend { font-weight: 600; padding: 0 6px; }
.filter-group input[type="date"], .filter-group input[type="number"], .filter-group select { width: 100%; margin-top: 6px; }
.checks { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow: auto; }
.check { display: flex; gap: 6px; align-items: center; font-size: 14px; }
.cpv-select input { width: 100%; }
.cpv-suggestions { list-style: none; margin: 4px 0; padding: 0; max-height: 240px; overflow: auto; border: 1px solid #eee; border-radius: 6px; }
.cpv-suggestions li { padding: 6px 8px; cursor: pointer; }
.cpv-suggestions li:hover { background: #f3f4f6; }
.cpv-code { font-family: monospace; }
.cpv-path { font-size: 12px; color: #666; }
.chip .hint { color: #2563eb; font-style: normal; font-size: 12px; }
.chip button { margin-left: 6px; border: none; background: none; cursor: pointer; }
.more { margin: 16px auto; display: block; }
@media (max-width: 800px) { .layout { flex-direction: column; } .filter-panel { flex-basis: auto; width: 100%; } }
```

- [ ] **Step 4: Verify build and run all UI tests**

Run: `cd search-ui && npm run build && npm test`
Expected: build succeeds; all vitest suites pass.

- [ ] **Step 5: Manual smoke test**

Run the dev server (`npm run dev`) against the deployed API and verify: (a) text search still works; (b) clearing the query + selecting a CPV and a status returns filtered, date-sorted results; (c) "Cargar más" advances results; (d) result cards show CPV labels.

- [ ] **Step 6: Commit**

```bash
git add search-ui/src/App.jsx search-ui/src/components/ResultCard.jsx search-ui/src/styles.css
git commit -m "feat: wire filter panel + browse mode + pagination into search UI"
```

---

## Self-Review Notes

- **Spec coverage:** §3 filter table → Tasks 2/3; q-optional + browse + sort → Task 3; CPV prefix → Tasks 2/3 (+ conditional Task 4); tokenization risk → Task 4; static codelist JSON → Task 1; CPV typeahead + breadcrumbs + non-leaf hint → Tasks 5/7; other filters → Task 8; pagination → Tasks 3/9; result-card decoding → Task 9; tests → Tasks 1/2/5/6. All sections covered.
- **Type consistency:** `build_where`/`where_to_gql`/`build_sort`/`sort_to_gql` signatures match between Tasks 2 and 3; `cpvLevel`/`cpvPath` signatures match between Tasks 5, 7, 9; `buildQuery`/`search` match between Tasks 6 and 9; `FilterPanel`/`CpvSelect` props match between Tasks 7, 8, 9.
- **No placeholders:** every code step contains full implementation.
```
