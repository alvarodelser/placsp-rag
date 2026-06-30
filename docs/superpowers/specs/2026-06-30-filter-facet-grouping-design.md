# Filter Facet Grouping — Resultado, Tipo, Procedimiento

**Date:** 2026-06-30
**Status:** Approved (design)

## Problem

In `FilterWorkspace`, the categorical facets **Resultado**, **Tipo de contrato**, and
**Procedimiento** are rendered as flat `MultiCheckIcons` grids that iterate the raw codelist
maps in arbitrary code order (11, 11, and 15 codes respectively). This exposes legacy codes,
provisional/definitivo duplicates, and niche variants the user does not need to reason about.

`Estado` already has a *logical* spatial layout (the `StatusLifecycle` flow diagram). We want
the three categorical facets arranged by meaning and **simplified** by folding legacy/variant
codes into broader cards.

## Goal

Replace the three flat grids with **grouped, simplified** layouts where each card represents a
*set* of underlying codes. Clicking a card toggles all of its codes in the filter; the card's
count is the sum of its codes' counts. No backend change — the API still filters on granular
codes.

## Final Groupings

One card = a set of codes. Counts sum across the set.

### Resultado — 3 cards (was 11)
| Card | Codes | Color |
|---|---|---|
| Adjudicado | 1, 2, 8, 9, 10, 11 | green |
| Desierto | 3, 6, 7 | gray |
| Cancelado | 4, 5 | red |

### Tipo — 4 cards (was 11)
| Card | Codes |
|---|---|
| Obras | 3, 31, 32 |
| Servicios | 2, 21, 22 |
| Suministros | 1 |
| Otros | 40, 50, 7, 8 |

### Procedimiento — 6 cards + Otros (was 15), on a concurrence axis
Laid left→right: *más concurrencia → más directo*. "Otros" sits off-axis.

| Card | Codes |
|---|---|
| Abierto | 1 |
| Abierto simplificado | 9 |
| Restringido | 2 |
| Negociado | 3, 4, 5, 10, 11, 13 |
| Derivados | 7, 12 |
| Contrato menor | 6 |
| Otros (off-axis) | 8, 100, 999 |

## Architecture

### New shared module: `src/facetGroups.js`
Single source of truth for groupings, imported by both the workspace components and
`ActiveFilters`.

Exports per facet (`RESULT_GROUPS`, `TYPE_GROUPS`, `PROC_GROUPS`), each an ordered array of:
```js
{ key: 'adj', label: 'Adjudicado', Icon: Trophy, color: 'green', codes: ['1','2','8','9','10','11'] }
```
`color` is optional (used by Resultado). Icons move here from the per-code maps currently in
`FilterWorkspace` (`RESULT_ICONS`/`TYPE_ICONS`/`PROC_ICONS` are removed; one icon per group).

Helpers (pure, unit-tested):
- `groupActive(group, value)` → `true` iff every code in `group.codes` is in `value`.
- `groupCount(group, counts)` → sum of `counts[code]` over `group.codes` (treats missing as 0; returns null if all missing).
- `toggleGroup(group, value)` → new value array: if active, remove all `group.codes`; else add the missing ones.
- `codeToGroup(field, code)` → the group label for a granular code, or null. Used by `ActiveFilters` to collapse chips.

### New component: `GroupedFacet` (Resultado + Tipo)
Both are a flat grid of merged cards — same component.
Props: `{ groups, value, counts, onChange }`.
Renders a `FacetCard` per group (reuses the existing `mci-card` visual: icon + label + summed
count). Optional `color` tints the active state. `onChange(toggleGroup(group, value))` on click.

### New component: `ProcedureAxis` (Procedimiento)
Props: `{ groups, value, counts, onChange }`.
Renders the on-axis groups in order along a horizontal gradient strip labelled
*"más concurrencia ◀──▶ más directo"*, with the `Otros` group on a separate off-axis row below.
Same `FacetCard` + `toggleGroup` mechanics.

### Shared `FacetCard`
Extract the card button markup from `MultiCheckIcons` into a small reusable component
`{ label, Icon, active, count, color, onToggle }` so all three layouts share it.

### `FilterWorkspace.jsx` changes
- Replace the three `MultiCheckIcons` usages: `result` and `contract_type` → `GroupedFacet`
  (with `RESULT_GROUPS` / `TYPE_GROUPS`); `procedure` → `ProcedureAxis` (`PROC_GROUPS`).
- Remove `RESULT_ICONS`, `TYPE_ICONS`, `PROC_ICONS` and the `MultiCheckIcons` import.
- Lazy-tab fetching (`resultDist`/`typeDist`/`procedureDist`) and `setList` wiring are unchanged.

### `ActiveFilters.jsx` changes
For `result`/`contract_type`/`procedure`, collapse the active granular codes into **one chip
per group** using `codeToGroup`. The chip label is the group label; removing it clears **all**
of that group's codes (not just one). Other fields (cpv, nuts, status, dates, budget) keep
their current per-value chip behavior.

### Removals
- Delete `MultiCheckIcons.jsx`, its test, and the `/* MultiCheckIcons */` block in `styles.css`
  (now dead). `MultiCheck.jsx` (a different component) is untouched.

### CSS (`styles.css`)
- Grid styles for `GroupedFacet` (reuse/rename `mci-grid` card styles).
- Axis styles for `ProcedureAxis`: the gradient strip, segment labels, off-axis row.
- Per-color active tints for Resultado (green/gray/red).

## Active-state semantics

- A group card is **active** iff *all* its codes are selected. A partial set (only possible via
  externally-supplied filters, e.g. a saved URL) renders as inactive; one click adds the rest.
  Since these components are the only writers of these filter fields, partial states do not
  arise in normal use.
- Removing a group chip in `ActiveFilters` removes the entire code-set.

## Testing

- `facetGroups.test.js`: `groupActive`, `groupCount`, `toggleGroup` (add/remove full set),
  `codeToGroup` round-trips; assert each code appears in exactly one group per facet (no
  overlap, no orphan within the displayed set).
- `GroupedFacet.test.jsx`: clicking a card emits the full code-set; summed count renders;
  active styling reflects all-codes-present.
- `ProcedureAxis.test.jsx`: on-axis order, Otros off-axis, toggle mechanics.
- `ActiveFilters.test.jsx` (update): grouped fields render one chip per group; remove clears
  the whole set.
- `FilterWorkspace.test.jsx` (update): the three tabs render the new components.

## Out of scope

- No backend/API changes.
- No change to `Estado`, `CPV`, `Ubicación`, `Fechas`, `Presupuesto`.
- No flow arrows inside Resultado (collapsed away by the simplification).
</content>
</invoke>
