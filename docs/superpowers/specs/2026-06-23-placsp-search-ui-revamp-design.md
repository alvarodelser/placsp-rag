# PLACSP Search UI Revamp — Design Spec

**Date:** 2026-06-23
**Status:** Approved design, pending spec review

## 1. Goal

Improve the PLACSP search UI (`search-ui/`, React + Vite) into a streamlined,
minimal, attractive interface. Five threads, one cohesive sub-project:

1. Restructure filters into a **bookmark rail + sliding drawer** instead of an
   always-visible sidebar.
2. Add **CPV subcode drill-down** so a selected code can be refined to a
   narrower one.
3. Replace the date/budget inputs with **range controls**: a logarithmic budget
   dual-slider and a publication-date **timeline** with presets, plus a "Solo
   con plazo abierto" toggle.
4. Fix the **empty-query search error** and make API errors degrade gracefully.
5. A **cohesive minimal visual refresh** across the whole app.

All work is in `search-ui/`. The search API (`search-api/`) is unchanged except
for a deployment verification (it already supports browse mode and all filter
params from the prior feature).

## 2. Scope

**In scope**
- Bookmark rail (right edge) of filter tabs with active-count badges; one drawer
  open at a time (close on re-click / outside-click / Esc); an active-filters
  chip row with clear-all.
- CPV chips expandable into direct-children drill-down that **replaces** (narrows)
  the selection; new `cpvChildren` helper.
- Reusable dual-thumb `RangeSlider`; `BudgetRange` (log scale + synced numeric
  inputs); `DateTimeline` (publication range + presets + "open only" toggle).
- Graceful empty-search handling and readable API errors.
- Full `styles.css` refresh (palette, spacing, borders, type; cards quieted).
- Deployment step + verification for the browse-capable API.

**Out of scope (YAGNI)**
- Any change to the search API code, schema, or codelists.
- New runtime dependencies (slider built custom; no UI libraries).
- Saved searches, URL deep-linking, facet counts, infinite scroll.
- Result-card content changes beyond visual restyle and existing CPV/NUTS
  decoding.

## 3. Architecture & components

### 3.1 New files (`search-ui/src/`)
- `components/FilterRail.jsx` — vertical bookmark tabs on the right edge; each
  tab shows its label and an active-count badge; click selects/toggles the open
  drawer.
- `components/FilterDrawer.jsx` — sliding overlay panel rendering the active
  tab's filter content; closes on re-click, outside-click, and `Escape`.
- `components/ActiveFilters.jsx` — removable chips summarizing all active
  filters above the results, with a "Limpiar" clear-all.
- `components/RangeSlider.jsx` — reusable dual-thumb slider primitive built from
  two overlaid `<input type="range">`, parameterized by a value↔position
  mapping (so the same component drives both linear-date and log-budget axes).
- `components/BudgetRange.jsx` — `RangeSlider` on a **logarithmic** scale (~€1k
  to €100M) bound to `budget_min`/`budget_max`, with two synced numeric inputs
  for exact entry.
- `components/DateTimeline.jsx` — `RangeSlider` over publication dates (lower
  bound `START_YEAR = 2019`, upper bound today) bound to `pub_from`/`pub_to`;
  preset buttons **Último mes / 3 meses / Año / Todo**; a "Solo con plazo
  abierto" checkbox bound to `open_only`.
- `components/MultiCheck.jsx` — the checkbox-list picker (extracted from the old
  `FilterPanel`) reused for status/result/contract_type/procedure.
- `filters.js` — pure helpers: `filtersToParams(filters)` (maps UI state to API
  params, e.g. `open_only` → `deadline_from = todayISO()`), the budget log-scale
  mapping (`budgetToPos`, `posToBudget`), and `activeFilterList(filters)` (for
  the chip row and rail badges). No React imports.

### 3.2 Modified files
- `App.jsx` — owns `filters` state, which drawer is open, run/browse logic, and
  graceful empty handling. Renders search form, `FilterRail`, `FilterDrawer`,
  `ActiveFilters`, results.
- `components/CpvSelect.jsx` — selected chips gain an expandable `▾ subcódigos`
  drill-down using `cpvChildren`; clicking a child replaces the chip.
- `cpv.js` — add `cpvChildren(code, cpvMap)`.
- `styles.css` — full cohesive refresh; styles for rail, drawer, slider, chips.
- `components/FilterPanel.jsx` — **removed** (replaced by rail/drawer + content
  components).

## 4. Filter UI behavior

- **Rail tabs:** `CPV`, `Ubicación`, `Estado`, `Resultado`, `Tipo`,
  `Procedimiento`, `Fechas`, `Presupuesto`. Each shows an active count derived
  from `activeFilterList`. The rail is fixed to the right edge; on narrow
  screens (≤800px) it collapses to a horizontal bar above results.
- **Drawer:** opening a tab renders that tab's content component. Re-clicking the
  open tab, clicking outside the drawer, or pressing `Escape` closes it. Drawer
  state is a single `openTab` string (or `null`).
- **Active filters:** `ActiveFilters` lists each active value as a removable
  chip; removing updates `filters`. "Limpiar" resets to `EMPTY`.

## 5. CPV drill-down

- `cpvChildren(code, cpvMap)`: returns the **direct** children of `code` — the
  codes in `cpvMap` whose significant prefix extends `code` by exactly one CPV
  level (division→group→class→category→detail), excluding `code` itself. Derived
  from the digit structure (reuses the `cpvLevel`/normalize logic).
- In `CpvSelect`, a selected chip renders a `▾ subcódigos` toggle when
  `cpvChildren(code).length > 0`. Expanding lists the children (`code · label`);
  clicking one calls `onChange` with the parent replaced by the child. Drilling
  is recursive (the new chip can be expanded again).

## 6. Range controls

### 6.1 RangeSlider primitive
- Props: `min`, `max`, `value: [lo, hi]`, `onChange([lo, hi])`, and an optional
  `scale` object `{ toPos(v), fromPos(p) }` defaulting to identity (linear).
- Implemented as two overlaid native range inputs over `[0, 1000]` position
  units; values are mapped through `scale`. Keeps both thumbs from crossing.

### 6.2 BudgetRange
- Log scale: `budgetToPos`/`posToBudget` map €1,000–€100,000,000 onto the slider
  position so the low end is navigable. Below-min reads as €0/no lower bound;
  above-max reads as "€100M+/no upper bound".
- Two numeric inputs (`desde`/`hasta`) stay in sync with the thumbs; editing
  either updates `budget_min`/`budget_max`. Values shown formatted (es-ES).

### 6.3 DateTimeline
- Timeline from `START_YEAR-01-01` to today (linear), two thumbs bound to
  `pub_from`/`pub_to` (ISO `YYYY-MM-DD`).
- Presets set the range: **Último mes** (today−1m → today), **3 meses**,
  **Año** (today−1y → today), **Todo** (clears `pub_from`/`pub_to`).
- "Solo con plazo abierto" checkbox toggles `open_only`; when on,
  `filtersToParams` adds `deadline_from = today`.

## 7. State & data flow

- `EMPTY` filter shape (UI state):
  `{ cpv:[], nuts:[], status:[], result:[], contract_type:[], procedure:[],
  pub_from:'', pub_to:'', budget_min:'', budget_max:'', open_only:false,
  sort:'' }`.
  (`deadline_from`/`deadline_to` are no longer UI state; deadline filtering is
  expressed via `open_only`.)
- On submit/run: `params = { q, mode, k, offset, ...filtersToParams(filters) }`
  → `search(params)` (existing `api.js`). `filtersToParams` drops empty values
  and maps `open_only` → `deadline_from`.
- `hasFilters` continues to exclude `sort` (and `open_only=false` counts as
  inactive).

## 8. Empty-search & error handling

- **No query and no active filters:** show a friendly inline prompt ("Escribe
  una consulta o aplica un filtro"); the submit button reads "Filtrar" but the
  run is a no-op with a brief hint — never a network call, never an error.
- **No query but filters active:** browse request (already supported).
- **API/network error:** render the message in the existing `.err` style,
  readable, without crashing.
- **Deployment:** the browse-capable API (prior feature, commit `b7004c5`) must
  be deployed. The plan includes a verification step:
  `curl ".../api/search?cpv=45&k=3"` should return browse results, not a 422.
  If the deployed API still 422s on empty `q`, that is the live root cause of
  the reported error and is resolved by deploying the updated API.

## 9. Visual refresh

- One token system in `styles.css`: a calm neutral palette plus a single accent;
  generous spacing; hairline (1px, low-contrast) borders; a tightened type
  scale. Result cards become quieter with clear title→meta→snippet hierarchy.
  Rail, drawer, sliders, chips, and badges all consume the same tokens so the UI
  reads as one system. No new fonts or dependencies.

## 10. Testing

- **Unit (vitest):**
  - `cpvChildren` — direct-children correctness, including gaps and leaves.
  - `budgetToPos`/`posToBudget` — round-trip and endpoint behavior.
  - `filtersToParams` — empty-value dropping, `open_only` → `deadline_from`,
    leaving other params intact.
  - `activeFilterList` — counts/labels for the rail badges and chip row.
- **Build/manual:** `npm run build` for all components; manual smoke covering
  rail/drawer open-close, CPV drill-down, budget/date sliders, presets, "open
  only", empty-search prompt, and an end-to-end filtered browse.

## 11. Resolved decisions

- Filter layout = **bookmark rail (right edge) + drawer overlay**.
- CPV drill-down = **replace/narrow**.
- Budget = **log dual-slider + synced numeric inputs**.
- Dates = **publication timeline + presets + "open only" toggle**.
- Restyle = **cohesive minimal refresh** (includes result cards).
- Date lower bound = **2019**; slider primitive is **custom** (no new deps).
