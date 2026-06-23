# PLACSP Search UI Redesign — Design

**Date:** 2026-06-24
**Status:** Approved for planning
**Scope:** Full redesign of the `search-ui` SPA plus a new aggregation endpoint in `search-api`.

## Goal

Replace the current 8-tab bookmark rail + cramped floating drawer with a focused, minimal
filter **workspace** that hosts genuinely interactive views — an explorable CPV tree, a
choropleth map of Spain, and density-backed range timelines — give live feedback while
filtering, restyle the whole app to a clean "Institutional indigo" aesthetic with Phosphor
icons, and move the relevance control to an attractive colored button on the right of each
result card.

## Design Direction

- **Aesthetic:** minimal, crisp, light theme — "Institutional indigo". Soft neutral grays,
  a confident indigo primary accent used sparingly. Trustworthy/modern public-sector feel.
- **Typography:** Inter (with system-font fallback stack).
- **Icons:** Phosphor (`@phosphor-icons/react`), regular weight, used throughout (tabs,
  buttons, badges, relevance control).
- **Color usage:** accent restrained everywhere except the relevance button, which is the
  one boldly-colored element (filled indigo when active).
- A light/dark toggle is explicitly **out of scope** for this effort (possible later).

## Layout & Interaction Model

The chosen model is a single **"Filtros" workspace** (not a per-tab drawer, not a top
filter bar).

- **Header** keeps its current function — query input, search-mode select, `Buscar`,
  `Explorar` — restyled. It gains one new control: a **`⚙ Filtros (n)`** button (Phosphor
  `SlidersHorizontal`) with a badge showing the number of active filters.
- The vertical bookmark rail and the floating drawer are **removed**.
- The **results view** is kept clean: a row of active-filter chips (removable) above the
  result cards. No filter controls compete with reading results.
- Clicking **Filtros** opens a **full-overlay filter workspace** with three zones:
  1. **Left — category list.** CPV, Ubicación, Fechas, Presupuesto, Estado, Resultado,
     Tipo, Procedimiento. Each row: Phosphor icon + label + selected-count badge.
     Selecting a category swaps the center pane.
  2. **Center — rich view** for the active category (see below).
  3. **Right — live results.** A slim column showing a **live total count** plus a preview
     list of top matching licitaciones, refreshing as filters change. The user never loses
     sight of what they are narrowing.
- The workspace closes back to the (now filtered) results list. Filters apply live while
  the workspace is open.

## Rich Views (center pane)

### CPV — Miller columns + search
Finder-style cascading drill-down: división (2-digit) → grupo → clase → categoría → … up
to 8-digit codes. Clicking an item slides its children into the next column; the active
path stays highlighted for context. A **search box on top** filters/jumps to any node by
code or description (most users know a keyword, not a code). Selected codes appear as
removable chips below the columns; selecting a parent implies its descendants (existing
filter semantics). Reuses `cpv.js` (`cpvLevel`, `cpvPath`, `cpvChildren`) and `cpv.json`.

### Ubicación — choropleth heatmap of Spain
An SVG map of Spain where regions are **shaded by result count** for the current filter set
(instant "where is the activity" insight). Click a region to toggle it as a filter
(selected regions get a distinct outline) and a synced chip/list mirrors the selection. A
toggle switches **Comunidades (NUTS-2) ⇄ Provincias (NUTS-3)**; clicking a community can
drill into its provinces.

- **Geometry source:** Eurostat **Nuts2json**
  (`https://raw.githubusercontent.com/eurostat/Nuts2json/master/pub/v2/2024/4326/<scale>/<level>.json`),
  level `2.json` (communities) and `3.json` (provinces), WGS84 (EPSG:4326), scale `10M`
  (fallback `20M` if too heavy). The file is **filtered to `ES*` NUTS codes and baked into
  the repo at build time** (`src/geo/spain-nuts2.json`, `src/geo/spain-nuts3.json`) — no
  runtime dependency on GitHub. If the published file is TopoJSON, the build step converts
  it to GeoJSON.
- **Rendering:** plain SVG `<path>` elements projected with `d3-geo` (no heavyweight map
  library). Canary Islands kept at true coordinates (inset optional, deferred).
- **Shading data:** per-region counts come from the new `/api/facets` endpoint.

### Fechas — dual-handle slider with subtle density area
A clean horizontal timeline with two draggable handles. Behind it, a **very subtle smoothed
area plot** (sparkline-style) shows the monthly volume of licitaciones — informative but
quiet. A **Publicación ⇄ Plazo de presentación** axis switch chooses which date the range
and density refer to; the old `open_only` ("Plazo abierto") becomes a quick preset on the
Plazo axis. Quick presets: Último mes / 3 meses / Año. Density data from `/api/facets`.

### Presupuesto — same slider + subtle density area, log-scaled
Reuses the `DensitySlider` component on a **logarithmic** budget axis (existing
`budgetToPos`/`posToBudget` from `filters.js`). Subtle density area shows budget
distribution; two handles set `budget_min`/`budget_max`.

### Estado / Resultado / Tipo / Procedimiento — multi-select checklists
Clean, restyled multi-select lists (evolved `MultiCheck`) driven by the existing codelists
(`status.json`, `result.json`, `contract_type.json`, `procedure.json`).

## Result Card

Restyled minimal card. The **relevance control becomes a filled, colored full-height
gutter on the right edge** of the card — a generous target with a Phosphor `ThumbsUp` and
"Relevante" label, indigo-filled when active. The body holds: badges (categoría / tipo /
estado), the title (linked to `source_url`), órgano contratante, money figures, CPV chips,
location · date, and the content snippet. The feedback wiring
(`sendFeedback`/`removeFeedback`, optimistic toggle, session id) is unchanged.

## Backend — new `/api/facets` endpoint

A new `GET /api/facets` accepting the **same filter query params** as `/api/search`
(`q`, `cpv`, `nuts`, `status`, …, `budget_min/max`, date ranges). It reuses
`filters.build_where` and issues Weaviate **`Aggregate`** queries, returning:

- `total` — true count of matching objects (`Aggregate { … { meta { count } } }`).
- `nuts` — `{ regionCode: count }` grouped by the NUTS field, for the map heatmap.
- `dates` — monthly buckets `[{ month, pub_count, plazo_count }]` for the density areas.
- `budget` *(optional/nice-to-have)* — coarse budget buckets for the budget density.
- `cpv` *(optional/deferrable)* — division-level counts.

`/api/search` is also extended to return a real **`total`** so the UI's "Cargar más"
pagination stops inferring from `count === K`.

### Date-bucketing risk and fallback
Weaviate `Aggregate` cannot bucket a date field into months natively. The server therefore
computes the monthly `dates` buckets by issuing a **bounded set of per-month `Aggregate`
count queries** (e.g. a trailing 24–36 month window derived from the active range). This is
the heaviest new piece.

**Fallback (if too expensive):** keep the dual-handle slider **without** the density area,
or approximate the density from a capped client-side sample of result dates. The slider and
range filtering work regardless; the density area is the degradable enhancement.

## Frontend Architecture

**New components / modules:**
- `components/FilterWorkspace.jsx` — overlay shell; renders the three zones, owns
  category selection, fetches facets, hosts the live-count + preview column.
- `components/CpvMiller.jsx` — Miller-column CPV explorer + search.
- `components/SpainMap.jsx` — d3-geo SVG choropleth, level toggle, selection.
- `components/DensitySlider.jsx` — shared dual-handle slider + subtle density area; props
  drive linear (dates) vs log (budget) scaling and the density series.
- `components/LiveResults.jsx` — live total count + preview list for the right zone.
- `icons.js` — central Phosphor icon re-exports.
- `geo/spain-nuts2.json`, `geo/spain-nuts3.json` — baked, ES-filtered geometries.
- `scripts/build-spain-geo.mjs` — fetch Nuts2json, filter `ES*`, convert to GeoJSON, write
  to `src/geo/`. Run manually / on demand (geometry rarely changes).

**Reworked:**
- `App.jsx` — workspace open/close state, facets fetching, real `total` for pagination,
  active-filter management.
- `ResultCard.jsx` — new layout + right-side colored relevance gutter.
- `MultiCheck.jsx`, `ActiveFilters.jsx` — restyle.
- `styles.css` — new design-token set (indigo palette, spacing, radii, Inter), workspace
  and component styles.
- `api.js` — add `facets()` call; consume `total`.

**Retired:**
- `FilterRail.jsx`, `FilterDrawer.jsx` (replaced by workspace).
- `CpvSelect.jsx`, `NutsSelect.jsx` (replaced by `CpvMiller`/`SpainMap`).
- `RangeSlider.jsx`, `BudgetRange.jsx`, `DateTimeline.jsx` (folded into `DensitySlider`).

**New dependencies:**
- `@phosphor-icons/react` (icons)
- `d3-geo` (map projection/paths)
- `topojson-client` (only if the Nuts2json source is TopoJSON; used at build time)

## Data Flow

1. User edits filters in the workspace → debounced `facets()` + `search()` calls with the
   current filter params.
2. `facets()` returns `total` + `nuts` + `dates` → drives the live count, map shading, and
   slider density areas.
3. `search()` returns the preview/results list with a real `total`.
4. Closing the workspace leaves the filters applied; the main results list reflects them.
5. Relevance toggles post feedback exactly as today.

## Error Handling

- Facets endpoint failure degrades gracefully: map renders unshaded (still selectable),
  sliders render without density, live count hidden — filtering still works.
- Map geometry is a baked local asset, so it cannot fail at runtime; a missing file is a
  build error caught before deploy.
- Existing search/feedback error handling (error banner, optimistic revert) is preserved.

## Testing

- **Pure logic (vitest):** cpv helpers, filter→params, budget log scale, NUTS `ES*`
  filtering of GeoJSON, facets param building.
- **Backend (pytest):** `/api/facets` GraphQL/Aggregate construction and filter reuse,
  mirroring `test_filters.py`; the date-bucketing window logic.
- **Component smoke tests:** workspace open/close, category switching, relevance toggle.

## Out of Scope

- Light/dark theme toggle.
- Canary Islands map inset (regions still shown at true coordinates).
- CPV division-count facets and budget-bucket facets (nice-to-have; may be deferred).
- Any change to ingestion or the Weaviate schema.
