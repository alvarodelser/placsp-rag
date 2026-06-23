# PLACSP Search — Structured Filtering — Design Spec

**Date:** 2026-06-23
**Status:** Approved design, pending spec review

## 1. Goal

Extend the existing PLACSP search stack (FastAPI `search-api` + React `search-ui`
over Weaviate) so users can **filter** results by structured fields — dates, CPV
codes, status/result, contract type, procedure, geography, and budget — in
addition to (or instead of) the current free-text semantic/keyword search. Users
must be able to **browse by filters alone**, with no text query. The UI must let
users select CPV codes in a **human-readable, hierarchical** way.

This is sub-project #1 of a larger plan. It deliberately unblocks but does not
implement: #2 profile-based matching, #3 chatbot (Ollama) + MCP. Those are
separate specs.

## 2. Scope

**In scope**

- Optional structured filters on `GET /api/search`, combined with AND.
- `q` becomes **optional**; with no query, results are filtered and sorted
  (default `publication_date desc`) — a browse mode.
- Hierarchical CPV matching by prefix (selecting a division matches the whole
  branch).
- A build-time script that converts the procurement codelists (`.gc` files) into
  static JSON bundled into the React app, so the UI can decode and search codes
  **client-side**. The API never deals in labels, only raw codes.
- UI: a filters panel with a CPV typeahead (code/label search with breadcrumb
  paths), multi-select chips for status/result/type/procedure, date-range
  pickers, budget min/max, a sort selector in browse mode, and active-filter
  chips.
- `offset`-based pagination alongside the existing `k` limit.

**Out of scope (YAGNI for this iteration)**

- Facet counts / aggregations.
- Saved searches, infinite scroll, URL-state deep linking (can come later).
- Any server-side codelist loading or codelist API endpoints.
- Profile matching, chatbot, MCP.

## 3. Field → filter → codelist mapping

Filterable fields, the Weaviate property they target, the match semantics, and
the codelist `.gc` file that decodes them in the UI:

| Filter param | Weaviate property | Type | Match | Codelist for labels |
|---|---|---|---|---|
| `q` (optional) | (vector / bm25) | str | relevance | — |
| `cpv` (repeatable) | `cpv` (`text[]`) | str | **prefix**, OR across values | `CPV2008-2.04.gc` |
| `status` (repeatable) | `status_code` | str | exact, OR | `SyndicationContractFolderStatusCode-2.04.gc` |
| `result` (repeatable) | `result_code` | str | exact, OR | `TenderResultCode-2.09.gc` |
| `contract_type` (repeatable) | `contract_type_code` | str | exact, OR | `ContractCode-2.08.gc` |
| `procedure` (repeatable) | `procedure_code` | str | exact, OR | `SyndicationTenderingProcessCode-2.07.gc` |
| `nuts` (repeatable) | `nuts` | str | **prefix**, OR | `NUTS-2021.gc` |
| `pub_from` / `pub_to` | `publication_date` | date | range (≥ / ≤) | — |
| `deadline_from` / `deadline_to` | `submission_deadline` | date | range | — |
| `budget_min` / `budget_max` | `budget_amount` | number | range | — |
| `sort` | (browse order) | str | `<field> <asc\|desc>` | — |
| `offset` | (pagination) | int | with `k` | — |

All present filters are combined with **AND**. Within a repeatable param, values
are combined with **OR** (e.g. `cpv=45&cpv=72` → CPV in branch 45 *or* 72).

## 4. API design (`search-api/search_api.py`)

### 4.1 Request

`GET /api/search` keeps `mode`, `k`, `alpha`. `q` changes from required to
optional. New params per the table above. Repeatable params use FastAPI
`Query(default=None)` typed as `list[str] | None`.

### 4.2 `where`-clause builder

A pure function `build_where(filters) -> dict | None` produces a Weaviate
GraphQL `where` object (or `None` when no filters are active):

- Each active field becomes one operand.
- Multi-value fields (`cpv`, `status`, …) become an `Or` of per-value operands;
  a single value is emitted directly (no wrapping `Or`).
- Prefix fields (`cpv`, `nuts`): `{path:[prop], operator:"Like", valueText:"<code>*"}`.
- Exact fields: `{path:[prop], operator:"Equal", valueText:"<code>"}`.
- Date ranges: `GreaterThanEqual` / `LessThanEqual` with `valueDate` (RFC3339).
- Budget range: `GreaterThanEqual` / `LessThanEqual` with `valueNumber`.
- All field operands are combined under a top-level `{operator:"And", operands:[…]}`.
  A single operand is emitted without the `And` wrapper.

This function is the **unit-test seam** — fully testable without Weaviate.

### 4.3 Query vs. browse paths

- **Query present** (`q` non-empty): build the existing `hybrid` / `nearVector` /
  `bm25` operator, and pass `where` as an additional argument to the same
  `Get` call. Ordering = relevance (no `sort`). `offset` supported.
- **Query absent** (browse): build a `Get` with `where`, `sort`, `limit:k`,
  `offset`. `sort` defaults to `publication_date desc`; the `sort` param accepts
  a small allowlist of `<field> <asc|desc>` (e.g. `publication_date`,
  `submission_deadline`, `budget_amount`) to avoid injection. If neither `q` nor
  any filter is provided, return an empty result set with a clear message rather
  than dumping the whole index.

GraphQL is assembled with the existing string-building approach, but all
user-supplied scalars go through `json.dumps` / numeric coercion / the sort
allowlist — never interpolated raw.

### 4.4 Response

Unchanged shape (`{query, mode, count, results, errors}`), plus echoing the
applied filters and `offset` for the UI. `query` may be `null` in browse mode.

## 5. CPV / NUTS prefix matching — risk note

Prefix `Like` matches against the inverted-index **tokens** of the `text[]`
property. CPV codes are stored as whole tokens (e.g. `45110000`), so `Like
"45*"` is expected to match. **The plan must verify this against the live
schema.** If the default `word` tokenization mis-handles codes that carry a
check-digit suffix (e.g. `45110000-1`), the fallback is to set `cpv` (and `nuts`)
to `tokenization:"field"` in `src/placsp/weaviate_schema.py` and re-index. Low
effort, flagged, not blocking the design.

## 6. Codelist JSON generation

New script `scripts/build_codelists_json.py`:

- Reuses `parse_gc` / `Codelists` from `src/placsp/codelists.py`.
- Reads the six `.gc` files named in §3 from `codelists/`.
- Emits one JSON per list into `search-ui/src/codelists/`:
  `cpv.json`, `status.json`, `result.json`, `contract_type.json`,
  `procedure.json`, `nuts.json`.
- Each JSON is a flat `{ "<code>": "<spanish label>" }` map.
- Output is **committed** to the repo (the codelists change rarely; regenerated
  by re-running the script) and bundled by Vite at build time.

No nested tree is emitted: CPV hierarchy is derived client-side from the flat map
(§7.1), keeping a single source of truth.

## 7. UI design (`search-ui/src/`)

### 7.1 CPV selector — typeahead + breadcrumbs

- A single search input. On input (debounced), filter `cpv.json` entries whose
  **code or label** contains the term; cap the rendered list (e.g. first 50).
- Each suggestion renders `‹code› · ‹label›` with a **breadcrumb** of ancestor
  labels (`Servicios › Saneamiento › Limpieza`). The breadcrumb is computed by a
  helper `cpvPath(code, cpvMap)` that walks prefix-ancestors: zero the deepest
  significant digit level repeatedly (category→class→group→division) and look up
  each ancestor in `cpvMap`, skipping gaps.
- Selecting a suggestion adds a **chip** (`code · short label`). If the selected
  code is a **non-leaf** (has descendants / trailing zeros), the chip shows a
  subtle `incluye sub-códigos` hint, because the API will prefix-match its whole
  branch.
- Helper `cpvLevel(code)` derives the level from digit positions for the
  non-leaf check.

### 7.2 Other filters

- `status`, `result`, `contract_type`, `procedure`: multi-select chip pickers
  populated from their JSON maps (label shown, code sent).
- `pub_*`, `deadline_*`: native date-range inputs.
- `budget_min` / `budget_max`: numeric inputs.
- A **sort** selector is shown only in browse mode (empty `q`).

### 7.3 Layout & state

- Filters live in a collapsible panel/drawer beside or above the results.
- Active filters appear as removable chips above the result list.
- `api.js` serializes all active filters into the query string (repeatable params
  for multi-value). Submitting with empty `q` triggers browse mode.
- Submitting with neither query nor filters shows the existing idle prompt.
- Pagination: a "load more" / next-page control advancing `offset`.

## 8. Testing

- **API** (`tests/` or `search-api` tests): unit tests for `build_where` covering
  each filter type, multi-value OR, date/number ranges, empty input (→ `None`),
  and the AND combination; the sort allowlist; the empty-input browse guard.
  No live Weaviate required.
- **Codelist script:** test `build_codelists_json.py` against a fixture `.gc`
  (e.g. existing `tests/fixtures/ContractCode.gc`) → expected `{code: label}`.
- **UI:** `cpvPath` / `cpvLevel` helpers unit-tested with representative codes;
  filter serialization tested; overall verified via the existing Vite build and
  manual smoke test.

## 9. Open decisions (resolved)

- CPV match = **hierarchical/prefix**.
- `q` = **optional**, browse mode with sort.
- Decode dicts = **static client-side JSON**, generated at build time.
- CPV UI = **typeahead + breadcrumbs** (no tree).
- Pagination = **offset** (simple); browse default sort = `publication_date desc`.
