# PLACSP Search UI Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the PLACSP search UI into a minimal, attractive interface with a bookmark-rail/drawer filter system, CPV subcode drill-down, log-budget and date-timeline range controls, an "Explorar" default preset, and graceful empty-search handling.

**Architecture:** All work is in `search-ui/` (React 18 + Vite). Pure logic (CPV children, filter→param mapping, presets, budget log-scale) lives in dependency-free modules (`cpv.js`, `filters.js`) and is unit-tested with Vitest. Presentational components consume those helpers and are verified via `npm run build` + manual smoke. A single `styles.css` token system unifies the look.

**Tech Stack:** React 18, Vite 5, Vitest 2. No new runtime dependencies.

## Global Constraints

- All changes are under `search-ui/`. Do **not** modify `search-api/`, the Weaviate schema, or the codelist JSON.
- **No new dependencies** (the dual-range slider is custom; deps stay `react`, `react-dom`).
- Run UI tests with `cd search-ui && npm test`; build with `cd search-ui && npm run build`. Both must stay green.
- Pure modules `cpv.js` and `filters.js` must have **no React imports** (so they unit-test cleanly).
- UI copy is **Spanish**, matching existing components.
- Filter API contract is unchanged: codes are raw; `status`/`result`/`contract_type`/`procedure` exact; `cpv`/`nuts` prefix; dates `pub_from`/`pub_to`/`deadline_from`; `budget_min`/`budget_max`; `sort` from the existing allowlist.
- **Explore preset** = `status: ['PUB','PRE']` + `sort: 'publication_date desc'`; it is the **default filter state on load** and the app **auto-runs the browse on mount**. It must NOT set `open_only`/`deadline_from`.
- `EMPTY` filter shape: `{ cpv:[], nuts:[], status:[], result:[], contract_type:[], procedure:[], pub_from:'', pub_to:'', budget_min:'', budget_max:'', open_only:false, sort:'' }`.

---

## File Structure

- `search-ui/src/cpv.js` (modify) — add `cpvChildren`.
- `search-ui/src/cpv.test.js` (modify) — tests for `cpvChildren`.
- `search-ui/src/filters.js` (new) — `EMPTY`, `EXPLORE`, `todayISO`, `filtersToParams`, `presetRange`, `activeFilterList`, `budgetToPos`, `posToBudget`.
- `search-ui/src/filters.test.js` (new) — tests for the above.
- `search-ui/src/components/RangeSlider.jsx` (new) — generic dual-thumb slider.
- `search-ui/src/components/BudgetRange.jsx` (new) — log-budget range.
- `search-ui/src/components/DateTimeline.jsx` (new) — publication timeline + presets + open toggle.
- `search-ui/src/components/MultiCheck.jsx` (new) — extracted checkbox-list picker.
- `search-ui/src/components/CpvSelect.jsx` (modify) — subcode drill-down.
- `search-ui/src/components/FilterRail.jsx` (new) — bookmark tabs + badges.
- `search-ui/src/components/FilterDrawer.jsx` (new) — sliding overlay panel.
- `search-ui/src/components/ActiveFilters.jsx` (new) — active-filter chip row + clear.
- `search-ui/src/App.jsx` (modify) — orchestration, explore default, auto-run, graceful empty.
- `search-ui/src/components/FilterPanel.jsx` (delete) — replaced.
- `search-ui/src/styles.css` (modify) — cohesive refresh + new component styles.

---

## Task 1: `cpvChildren` helper

**Files:**
- Modify: `search-ui/src/cpv.js`
- Test: `search-ui/src/cpv.test.js`

**Interfaces:**
- Consumes: existing `cpvLevel(code)`, `normalize` (private) in `cpv.js`.
- Produces: `cpvChildren(code: string, cpvMap: Record<string,string>) -> string[]` — the direct children (one CPV level deeper, sharing the prefix), sorted.

- [ ] **Step 1: Write the failing tests**

Add to `search-ui/src/cpv.test.js`:

```js
import { cpvChildren } from './cpv.js'

const TREE = {
  '45000000': 'Construcción',
  '45100000': 'Preparación de obras',
  '45200000': 'Construcción completa',
  '45210000': 'Edificios',
  '45211000': 'Viviendas',
}

describe('cpvChildren', () => {
  it('returns direct children one level deeper', () => {
    expect(cpvChildren('45000000', TREE)).toEqual(['45100000', '45200000'])
    expect(cpvChildren('45200000', TREE)).toEqual(['45210000'])
    expect(cpvChildren('45210000', TREE)).toEqual(['45211000'])
  })
  it('returns empty for a leaf', () => {
    expect(cpvChildren('45211000', TREE)).toEqual([])
  })
})
```

Note: `describe`/`it`/`expect` are already imported at the top of `cpv.test.js`; add only the new import and `describe` block. If the existing file imports them per-block, keep the file's existing style.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search-ui && npm test`
Expected: FAIL — `cpvChildren` is not exported.

- [ ] **Step 3: Implement `cpvChildren`**

Append to `search-ui/src/cpv.js`:

```js
export function cpvChildren(code, cpvMap) {
  const d = normalize(code)
  const parentLen = cpvLevel(code)
  if (parentLen >= 8) return []
  const prefix = d.slice(0, parentLen)
  const childLen = parentLen + 1
  const out = []
  for (const c of Object.keys(cpvMap)) {
    if (cpvLevel(c) === childLen && normalize(c).slice(0, parentLen) === prefix) {
      out.push(c)
    }
  }
  return out.sort()
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search-ui && npm test`
Expected: PASS (cpvChildren suite + existing cpv suites).

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/cpv.js search-ui/src/cpv.test.js
git commit -m "feat: cpvChildren helper for CPV subcode drill-down"
```

---

## Task 2: `filters.js` core — presets, params, active list

**Files:**
- Create: `search-ui/src/filters.js`
- Test: `search-ui/src/filters.test.js`

**Interfaces:**
- Produces:
  - `EMPTY` — the cleared filter object (exact shape in Global Constraints).
  - `EXPLORE` — `{ ...EMPTY, status: ['PUB','PRE'], sort: 'publication_date desc' }`.
  - `todayISO(date?: Date) -> string` (`YYYY-MM-DD`, UTC).
  - `filtersToParams(filters) -> object` — drops empty values, drops `open_only`, adds `deadline_from = todayISO()` when `open_only` is true.
  - `presetRange(name: 'month'|'quarter'|'year'|'all', today?: Date) -> {pub_from, pub_to}`.
  - `activeFilterList(filters) -> {field, value}[]` — one entry per active filter value.
- Consumed by: Tasks 5, 6, 9, 10, 11.

- [ ] **Step 1: Write the failing tests**

Create `search-ui/src/filters.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { EMPTY, EXPLORE, todayISO, filtersToParams, presetRange, activeFilterList } from './filters.js'

describe('EXPLORE preset', () => {
  it('is PUB+PRE sorted latest, no deadline', () => {
    expect(EXPLORE.status).toEqual(['PUB', 'PRE'])
    expect(EXPLORE.sort).toBe('publication_date desc')
    expect(EXPLORE.open_only).toBe(false)
    expect(filtersToParams(EXPLORE)).toEqual({ status: ['PUB', 'PRE'], sort: 'publication_date desc' })
  })
})

describe('filtersToParams', () => {
  it('drops empties for EMPTY', () => {
    expect(filtersToParams(EMPTY)).toEqual({})
  })
  it('maps open_only to deadline_from', () => {
    const p = filtersToParams({ ...EMPTY, open_only: true })
    expect(p.deadline_from).toBe(todayISO())
    expect('open_only' in p).toBe(false)
  })
  it('keeps non-empty values', () => {
    expect(filtersToParams({ ...EMPTY, cpv: ['45'], budget_min: '1000' }))
      .toEqual({ cpv: ['45'], budget_min: '1000' })
  })
})

describe('presetRange', () => {
  const ref = new Date('2025-06-23T00:00:00Z')
  it('computes year/month windows in UTC', () => {
    expect(presetRange('year', ref)).toEqual({ pub_from: '2024-06-23', pub_to: '2025-06-23' })
    expect(presetRange('month', ref)).toEqual({ pub_from: '2025-05-23', pub_to: '2025-06-23' })
  })
  it('clears the range for "all"', () => {
    expect(presetRange('all', ref)).toEqual({ pub_from: '', pub_to: '' })
  })
})

describe('activeFilterList', () => {
  it('is empty for EMPTY', () => {
    expect(activeFilterList(EMPTY)).toEqual([])
  })
  it('lists each status value', () => {
    expect(activeFilterList(EXPLORE)).toEqual([
      { field: 'status', value: 'PUB' },
      { field: 'status', value: 'PRE' },
    ])
  })
  it('includes dates, budget and open_only entries', () => {
    const list = activeFilterList({ ...EMPTY, pub_from: '2024-01-01', open_only: true, budget_min: '1000' })
    expect(list.map((e) => e.field)).toEqual(['dates', 'open_only', 'budget'])
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search-ui && npm test`
Expected: FAIL — cannot resolve `./filters.js`.

- [ ] **Step 3: Implement `filters.js`**

Create `search-ui/src/filters.js`:

```js
// Pure filter helpers (no React). Maps UI filter state to API params, defines
// the cleared (EMPTY) and default (EXPLORE) shapes, and derives the active
// filter list used by the chip row and rail badges.

export const EMPTY = {
  cpv: [], nuts: [], status: [], result: [], contract_type: [], procedure: [],
  pub_from: '', pub_to: '', budget_min: '', budget_max: '', open_only: false,
  sort: '',
}

export const EXPLORE = {
  ...EMPTY,
  status: ['PUB', 'PRE'],
  sort: 'publication_date desc',
}

export function todayISO(date = new Date()) {
  return date.toISOString().slice(0, 10)
}

export function filtersToParams(filters) {
  const out = {}
  for (const [k, v] of Object.entries(filters)) {
    if (k === 'open_only') continue
    if (v == null || v === '') continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  if (filters.open_only) out.deadline_from = todayISO()
  return out
}

export function presetRange(name, today = new Date()) {
  if (name === 'all') return { pub_from: '', pub_to: '' }
  const d = new Date(today.getTime())
  if (name === 'month') d.setUTCMonth(d.getUTCMonth() - 1)
  else if (name === 'quarter') d.setUTCMonth(d.getUTCMonth() - 3)
  else if (name === 'year') d.setUTCFullYear(d.getUTCFullYear() - 1)
  return { pub_from: todayISO(d), pub_to: todayISO(today) }
}

const LIST_FIELDS = ['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure']

export function activeFilterList(filters) {
  const out = []
  for (const f of LIST_FIELDS) {
    for (const v of filters[f] || []) out.push({ field: f, value: v })
  }
  if (filters.pub_from || filters.pub_to) {
    out.push({ field: 'dates', value: `${filters.pub_from || '…'} – ${filters.pub_to || '…'}` })
  }
  if (filters.open_only) out.push({ field: 'open_only', value: 'Plazo abierto' })
  if (filters.budget_min || filters.budget_max) {
    out.push({ field: 'budget', value: `${filters.budget_min || '0'} – ${filters.budget_max || '∞'}` })
  }
  return out
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search-ui && npm test`
Expected: PASS (filters suites + existing).

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/filters.js search-ui/src/filters.test.js
git commit -m "feat: filters.js — EMPTY/EXPLORE presets, filtersToParams, presetRange, activeFilterList"
```

---

## Task 3: budget log-scale helpers

**Files:**
- Modify: `search-ui/src/filters.js`
- Test: `search-ui/src/filters.test.js`

**Interfaces:**
- Produces: `budgetToPos(v: number|string) -> number` (0–1000) and `posToBudget(p: number) -> number` (€1,000–€100,000,000), inverse on a log scale.
- Consumed by: Task 5 (`BudgetRange`).

- [ ] **Step 1: Write the failing tests**

Add to `search-ui/src/filters.test.js`:

```js
import { budgetToPos, posToBudget } from './filters.js'

describe('budget log scale', () => {
  it('maps endpoints to 0 and 1000', () => {
    expect(budgetToPos(1000)).toBe(0)
    expect(budgetToPos(100000000)).toBe(1000)
  })
  it('clamps out-of-range inputs', () => {
    expect(budgetToPos(100)).toBe(0)
    expect(budgetToPos(1e12)).toBe(1000)
  })
  it('round-trips within 1%', () => {
    for (const v of [5000, 50000, 1000000, 20000000]) {
      const back = posToBudget(budgetToPos(v))
      expect(Math.abs(back - v) / v).toBeLessThan(0.01)
    }
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search-ui && npm test`
Expected: FAIL — `budgetToPos`/`posToBudget` not exported.

- [ ] **Step 3: Implement the scale**

Append to `search-ui/src/filters.js`:

```js
const B_MIN = 1000
const B_MAX = 100000000
const B_LMIN = Math.log(B_MIN)
const B_LSPAN = Math.log(B_MAX) - B_LMIN

export function budgetToPos(v) {
  const x = Math.max(B_MIN, Math.min(B_MAX, Number(v) || B_MIN))
  return Math.round(((Math.log(x) - B_LMIN) / B_LSPAN) * 1000)
}

export function posToBudget(p) {
  const t = Math.max(0, Math.min(1000, Number(p))) / 1000
  return Math.round(Math.exp(B_LMIN + t * B_LSPAN))
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search-ui && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add search-ui/src/filters.js search-ui/src/filters.test.js
git commit -m "feat: logarithmic budget scale helpers"
```

---

## Task 4: `RangeSlider` primitive

**Files:**
- Create: `search-ui/src/components/RangeSlider.jsx`

**Interfaces:**
- Produces: `<RangeSlider value={[lo, hi]} onChange={([lo,hi]) => void} scale={{ toPos(v)->0..1000, fromPos(p)->v }} />`. `value` is in domain units; thumbs cannot cross.
- Consumed by: Tasks 5, 6.

- [ ] **Step 1: Create the component**

Create `search-ui/src/components/RangeSlider.jsx`:

```jsx
// Generic dual-thumb slider. Two native range inputs overlaid on a track; the
// `scale` maps domain values <-> 0..1000 slider positions so the same control
// drives both the linear date axis and the logarithmic budget axis.
export default function RangeSlider({ value, onChange, scale }) {
  const loPos = scale.toPos(value[0])
  const hiPos = scale.toPos(value[1])

  function setLo(p) {
    const np = Math.min(Number(p), hiPos)
    onChange([scale.fromPos(np), value[1]])
  }
  function setHi(p) {
    const np = Math.max(Number(p), loPos)
    onChange([value[0], scale.fromPos(np)])
  }

  return (
    <div className="range-slider">
      <div className="range-track" />
      <div className="range-fill" style={{ left: `${loPos / 10}%`, right: `${100 - hiPos / 10}%` }} />
      <input className="range-thumb" type="range" min="0" max="1000" value={loPos} onChange={(e) => setLo(e.target.value)} />
      <input className="range-thumb" type="range" min="0" max="1000" value={hiPos} onChange={(e) => setHi(e.target.value)} />
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/RangeSlider.jsx
git commit -m "feat: reusable dual-thumb RangeSlider primitive"
```

---

## Task 5: `BudgetRange`

**Files:**
- Create: `search-ui/src/components/BudgetRange.jsx`

**Interfaces:**
- Consumes: `RangeSlider` (Task 4); `budgetToPos`/`posToBudget` (Task 3); `money` from `../format.js`.
- Produces: `<BudgetRange filters={obj} onChange={(patch) => void} />` where `patch` is `{ budget_min, budget_max }` (string values, '' = unbounded).

- [ ] **Step 1: Create the component**

Create `search-ui/src/components/BudgetRange.jsx`:

```jsx
import RangeSlider from './RangeSlider.jsx'
import { budgetToPos, posToBudget } from '../filters.js'

const SCALE = { toPos: budgetToPos, fromPos: posToBudget }
const B_MIN = 1000
const B_MAX = 100000000

export default function BudgetRange({ filters, onChange }) {
  const lo = filters.budget_min === '' ? B_MIN : Number(filters.budget_min)
  const hi = filters.budget_max === '' ? B_MAX : Number(filters.budget_max)

  function setRange([nlo, nhi]) {
    onChange({
      budget_min: nlo <= B_MIN ? '' : String(nlo),
      budget_max: nhi >= B_MAX ? '' : String(nhi),
    })
  }

  return (
    <div className="budget-range">
      <RangeSlider value={[lo, hi]} onChange={setRange} scale={SCALE} />
      <div className="range-inputs">
        <label>desde
          <input type="number" min="0" placeholder="0"
            value={filters.budget_min}
            onChange={(e) => onChange({ budget_min: e.target.value })} />
        </label>
        <label>hasta
          <input type="number" min="0" placeholder="100M+"
            value={filters.budget_max}
            onChange={(e) => onChange({ budget_max: e.target.value })} />
        </label>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/BudgetRange.jsx
git commit -m "feat: BudgetRange log-scale slider with synced numeric inputs"
```

---

## Task 6: `DateTimeline`

**Files:**
- Create: `search-ui/src/components/DateTimeline.jsx`

**Interfaces:**
- Consumes: `RangeSlider` (Task 4); `presetRange`, `todayISO` (Task 2).
- Produces: `<DateTimeline filters={obj} onChange={(patch) => void} />` where `patch` may set `{ pub_from, pub_to }` and `{ open_only }`.

- [ ] **Step 1: Create the component**

Create `search-ui/src/components/DateTimeline.jsx`:

```jsx
import RangeSlider from './RangeSlider.jsx'
import { presetRange, todayISO } from '../filters.js'

const START = Date.UTC(2019, 0, 1)
const END = Date.now()
const SPAN = END - START
const SCALE = {
  toPos: (ts) => Math.round(((ts - START) / SPAN) * 1000),
  fromPos: (p) => START + (p / 1000) * SPAN,
}

const PRESETS = [
  ['month', 'Último mes'],
  ['quarter', '3 meses'],
  ['year', 'Año'],
  ['all', 'Todo'],
]

function toTs(iso, fallback) {
  return iso ? Date.parse(`${iso}T00:00:00Z`) : fallback
}

export default function DateTimeline({ filters, onChange }) {
  const lo = toTs(filters.pub_from, START)
  const hi = toTs(filters.pub_to, END)

  function setRange([nlo, nhi]) {
    onChange({
      pub_from: nlo <= START ? '' : todayISO(new Date(nlo)),
      pub_to: nhi >= END ? '' : todayISO(new Date(nhi)),
    })
  }

  return (
    <div className="date-timeline">
      <div className="presets">
        {PRESETS.map(([name, label]) => (
          <button type="button" key={name} className="preset"
            onClick={() => onChange(presetRange(name))}>{label}</button>
        ))}
      </div>
      <RangeSlider value={[lo, hi]} onChange={setRange} scale={SCALE} />
      <div className="range-caption">
        publicación: {filters.pub_from || '…'} – {filters.pub_to || 'hoy'}
      </div>
      <label className="check open-toggle">
        <input type="checkbox" checked={filters.open_only}
          onChange={(e) => onChange({ open_only: e.target.checked })} />
        Solo con plazo abierto
      </label>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/DateTimeline.jsx
git commit -m "feat: DateTimeline publication range with presets and open-only toggle"
```

---

## Task 7: `MultiCheck` extracted picker

**Files:**
- Create: `search-ui/src/components/MultiCheck.jsx`

**Interfaces:**
- Produces: `<MultiCheck map={Record<string,string>} value={string[]} onChange={(string[]) => void} />` — a scrollable checkbox list; `map` is `{code: label}`, `value` is selected codes.
- Consumed by: Task 9 (drawer content for status/result/type/procedure).

- [ ] **Step 1: Create the component**

Create `search-ui/src/components/MultiCheck.jsx`:

```jsx
export default function MultiCheck({ map, value, onChange }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }
  return (
    <div className="checks">
      {Object.entries(map).map(([code, name]) => (
        <label key={code} className="check">
          <input type="checkbox" checked={value.includes(code)} onChange={() => toggle(code)} />
          {name}
        </label>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/MultiCheck.jsx
git commit -m "feat: extract MultiCheck checkbox-list picker"
```

---

## Task 8: CPV subcode drill-down

**Files:**
- Modify: `search-ui/src/components/CpvSelect.jsx`

**Interfaces:**
- Consumes: `cpvChildren` (Task 1); existing `cpvLevel`, `cpvPath`, `cpvMap`.
- Produces: unchanged `<CpvSelect value={string[]} onChange={fn} />`; selected chips now expand to direct children that replace the chip when clicked.

- [ ] **Step 1: Replace the chip-rendering block**

In `search-ui/src/components/CpvSelect.jsx`, update the import line:

```jsx
import { cpvLevel, cpvPath, cpvChildren } from '../cpv.js'
```

Add `useState` for tracking which chip is expanded — change the component's state line to include it, and replace the selected-chips block. Replace the existing `{value.length > 0 && ( ... )}` block with:

```jsx
      {value.length > 0 && (
        <div className="cpv-chips">
          {value.map((code) => {
            const kids = cpvChildren(code, cpvMap)
            const open = expanded === code
            return (
              <div className="cpv-chip-wrap" key={code}>
                <span className="chip">
                  {code} · {cpvMap[code] || '—'}
                  {cpvLevel(code) < 8 && <em className="hint"> (incluye sub-códigos)</em>}
                  {kids.length > 0 && (
                    <button type="button" className="drill" aria-label="Subcódigos"
                      onClick={() => setExpanded(open ? null : code)}>{open ? '▾' : '▸'}</button>
                  )}
                  <button type="button" onClick={() => remove(code)} aria-label="Quitar">✕</button>
                </span>
                {open && kids.length > 0 && (
                  <ul className="cpv-subcodes">
                    {kids.map((kc) => (
                      <li key={kc} onClick={() => { onChange(value.map((c) => (c === code ? kc : c))); setExpanded(kc) }}>
                        <span className="cpv-code">{kc}</span> · {cpvMap[kc] || '—'}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      )}
```

And add the `expanded` state next to the existing `term` state:

```jsx
  const [term, setTerm] = useState('')
  const [expanded, setExpanded] = useState(null)
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/CpvSelect.jsx
git commit -m "feat: CPV subcode drill-down (replace/narrow) in selected chips"
```

---

## Task 9: `FilterRail` + `FilterDrawer`

**Files:**
- Create: `search-ui/src/components/FilterRail.jsx`
- Create: `search-ui/src/components/FilterDrawer.jsx`

**Interfaces:**
- Consumes: `activeFilterList` (Task 2).
- Produces:
  - `<FilterRail tabs={[{id,label}]} counts={Record<string,number>} openTab={string|null} onOpen={(id)=>void} />`.
  - `<FilterDrawer title={string} onClose={()=>void}>{children}</FilterDrawer>` — renders an overlay panel; calls `onClose` on outside-click and `Escape`.
- Consumed by: Task 11 (`App`).

- [ ] **Step 1: Create `FilterRail`**

Create `search-ui/src/components/FilterRail.jsx`:

```jsx
export default function FilterRail({ tabs, counts, openTab, onOpen }) {
  return (
    <nav className="filter-rail">
      {tabs.map(({ id, label }) => (
        <button type="button" key={id}
          className={`rail-tab${openTab === id ? ' active' : ''}`}
          onClick={() => onOpen(openTab === id ? null : id)}>
          {label}
          {counts[id] > 0 && <span className="rail-badge">{counts[id]}</span>}
        </button>
      ))}
    </nav>
  )
}
```

- [ ] **Step 2: Create `FilterDrawer`**

Create `search-ui/src/components/FilterDrawer.jsx`:

```jsx
import { useEffect, useRef } from 'react'

export default function FilterDrawer({ title, onClose, children }) {
  const ref = useRef(null)

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) onClose() }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  return (
    <div className="filter-drawer" ref={ref}>
      <div className="drawer-head">
        <span>{title}</span>
        <button type="button" onClick={onClose} aria-label="Cerrar">✕</button>
      </div>
      <div className="drawer-body">{children}</div>
    </div>
  )
}
```

- [ ] **Step 3: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add search-ui/src/components/FilterRail.jsx search-ui/src/components/FilterDrawer.jsx
git commit -m "feat: bookmark FilterRail and sliding FilterDrawer"
```

---

## Task 10: `ActiveFilters` chip row

**Files:**
- Create: `search-ui/src/components/ActiveFilters.jsx`

**Interfaces:**
- Consumes: `activeFilterList` (Task 2); codelist JSON maps; `cpvMap`/`nutsMap` for labels.
- Produces: `<ActiveFilters filters={obj} onRemove={(field, value)=>void} onClear={()=>void} />`.
- Consumed by: Task 11 (`App`).

- [ ] **Step 1: Create the component**

Create `search-ui/src/components/ActiveFilters.jsx`:

```jsx
import { activeFilterList } from '../filters.js'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import statusMap from '../codelists/status.json'
import resultMap from '../codelists/result.json'
import typeMap from '../codelists/contract_type.json'
import procMap from '../codelists/procedure.json'

const MAPS = {
  cpv: cpvMap, nuts: nutsMap, status: statusMap,
  result: resultMap, contract_type: typeMap, procedure: procMap,
}

function labelFor({ field, value }) {
  const m = MAPS[field]
  if (m) return `${value} · ${m[value] || ''}`.trim()
  if (field === 'dates') return `Fechas: ${value}`
  if (field === 'budget') return `Presupuesto: ${value}`
  return value
}

export default function ActiveFilters({ filters, onRemove, onClear }) {
  const list = activeFilterList(filters)
  if (list.length === 0) return null
  return (
    <div className="active-filters">
      {list.map((e) => (
        <span className="chip" key={`${e.field}:${e.value}`}>
          {labelFor(e)}
          <button type="button" aria-label="Quitar" onClick={() => onRemove(e.field, e.value)}>✕</button>
        </span>
      ))}
      <button type="button" className="clear-all" onClick={onClear}>Limpiar</button>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd search-ui && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add search-ui/src/components/ActiveFilters.jsx
git commit -m "feat: ActiveFilters chip row with clear-all"
```

---

## Task 11: `App` orchestration + explore default

**Files:**
- Modify: `search-ui/src/App.jsx`
- Delete: `search-ui/src/components/FilterPanel.jsx`

**Interfaces:**
- Consumes: `search` (`api.js`), `filtersToParams`/`activeFilterList`/`EMPTY`/`EXPLORE` (`filters.js`), `FilterRail`, `FilterDrawer`, `ActiveFilters`, `CpvSelect`, `NutsSelect`, `MultiCheck`, `BudgetRange`, `DateTimeline`, codelist maps.

- [ ] **Step 1: Replace `App.jsx`**

Replace the contents of `search-ui/src/App.jsx` with:

```jsx
import { useEffect, useRef, useState } from 'react'
import { search } from './api.js'
import { EMPTY, EXPLORE, filtersToParams, activeFilterList } from './filters.js'
import FilterRail from './components/FilterRail.jsx'
import FilterDrawer from './components/FilterDrawer.jsx'
import ActiveFilters from './components/ActiveFilters.jsx'
import CpvSelect from './components/CpvSelect.jsx'
import NutsSelect from './components/NutsSelect.jsx'
import MultiCheck from './components/MultiCheck.jsx'
import BudgetRange from './components/BudgetRange.jsx'
import DateTimeline from './components/DateTimeline.jsx'
import ResultCard from './components/ResultCard.jsx'
import statusMap from './codelists/status.json'
import resultMap from './codelists/result.json'
import typeMap from './codelists/contract_type.json'
import procMap from './codelists/procedure.json'

const MODES = [['hybrid', 'Híbrida'], ['vector', 'Semántica'], ['keyword', 'Palabra clave']]
const K = 15

const TABS = [
  { id: 'cpv', label: 'CPV', fields: ['cpv'] },
  { id: 'nuts', label: 'Ubicación', fields: ['nuts'] },
  { id: 'status', label: 'Estado', fields: ['status'] },
  { id: 'result', label: 'Resultado', fields: ['result'] },
  { id: 'contract_type', label: 'Tipo', fields: ['contract_type'] },
  { id: 'procedure', label: 'Procedimiento', fields: ['procedure'] },
  { id: 'dates', label: 'Fechas', fields: ['dates', 'open_only'] },
  { id: 'budget', label: 'Presupuesto', fields: ['budget'] },
]

export default function App() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [filters, setFilters] = useState(EXPLORE)
  const [openTab, setOpenTab] = useState(null)
  const [state, setState] = useState({ status: 'idle' })
  const didMount = useRef(false)

  const browse = q.trim() === ''
  const hasFilters = activeFilterList(filters).length > 0

  async function run(offset = 0, f = filters, query = q) {
    if (query.trim() === '' && activeFilterList(f).length === 0) {
      setState({ status: 'idle' })
      return
    }
    setState({ status: 'loading' })
    try {
      const data = await search({ q: query.trim(), mode, k: K, offset, ...filtersToParams(f) })
      setState({ status: 'done', data })
    } catch (err) {
      setState({ status: 'error', message: err.message })
    }
  }

  // Auto-run the EXPLORE default once on mount.
  useEffect(() => {
    if (didMount.current) return
    didMount.current = true
    run(0, EXPLORE, '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function patch(p) { setFilters((f) => ({ ...f, ...p })) }
  function setList(field, vals) { patch({ [field]: vals }) }

  function removeFilter(field, value) {
    if (['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure'].includes(field)) {
      patch({ [field]: filters[field].filter((v) => v !== value) })
    } else if (field === 'dates') patch({ pub_from: '', pub_to: '' })
    else if (field === 'open_only') patch({ open_only: false })
    else if (field === 'budget') patch({ budget_min: '', budget_max: '' })
  }

  const counts = {}
  for (const e of activeFilterList(filters)) {
    const tab = TABS.find((t) => t.fields.includes(e.field))
    if (tab) counts[tab.id] = (counts[tab.id] || 0) + 1
  }

  function drawerContent(id) {
    switch (id) {
      case 'cpv': return <CpvSelect value={filters.cpv} onChange={(v) => setList('cpv', v)} />
      case 'nuts': return <NutsSelect value={filters.nuts} onChange={(v) => setList('nuts', v)} />
      case 'status': return <MultiCheck map={statusMap} value={filters.status} onChange={(v) => setList('status', v)} />
      case 'result': return <MultiCheck map={resultMap} value={filters.result} onChange={(v) => setList('result', v)} />
      case 'contract_type': return <MultiCheck map={typeMap} value={filters.contract_type} onChange={(v) => setList('contract_type', v)} />
      case 'procedure': return <MultiCheck map={procMap} value={filters.procedure} onChange={(v) => setList('procedure', v)} />
      case 'dates': return <DateTimeline filters={filters} onChange={patch} />
      case 'budget': return <BudgetRange filters={filters} onChange={patch} />
      default: return null
    }
  }

  const openTabDef = TABS.find((t) => t.id === openTab)

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda y filtros</div>
          <form onSubmit={(e) => { e.preventDefault(); run(0) }}>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza (o deja vacío y filtra)" autoFocus />
            <select value={mode} onChange={(e) => setMode(e.target.value)} title="Modo de búsqueda" disabled={browse}>
              {MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : browse ? 'Filtrar' : 'Buscar'}
            </button>
            <button type="button" className="explore-btn" onClick={() => { setFilters(EXPLORE); setQ(''); run(0, EXPLORE, '') }}>
              Explorar
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap layout">
          <section className="results">
            <ActiveFilters filters={filters} onRemove={removeFilter} onClear={() => { setFilters(EMPTY); setState({ status: 'idle' }) }} />

            {state.status === 'error' && <div className="err">Error: {state.message}</div>}

            {state.status === 'done' && (
              <>
                <div className="meta">{state.data.count} resultado(s) · modo {state.data.mode}</div>
                {state.data.errors && <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>}
                {state.data.results.length > 0 ? (
                  <>
                    {state.data.results.map((r) => <ResultCard key={r._id || r.syndication_id} r={r} />)}
                    {state.data.count === K && (
                      <button className="more" onClick={() => run((state.data.offset || 0) + K)}>Cargar más</button>
                    )}
                  </>
                ) : <div className="empty">Sin resultados.</div>}
              </>
            )}

            {state.status === 'idle' && (
              <div className="empty">Escribe una consulta o aplica un filtro.</div>
            )}
          </section>

          <FilterRail tabs={TABS} counts={counts} openTab={openTab} onOpen={setOpenTab} />
          {openTabDef && (
            <FilterDrawer title={openTabDef.label} onClose={() => setOpenTab(null)}>
              {drawerContent(openTab)}
            </FilterDrawer>
          )}
        </div>
      </main>
    </>
  )
}
```

- [ ] **Step 2: Delete the obsolete FilterPanel**

Run: `git rm search-ui/src/components/FilterPanel.jsx`

- [ ] **Step 3: Verify build and tests**

Run: `cd search-ui && npm run build && npm test`
Expected: build succeeds; all vitest suites pass.

- [ ] **Step 4: Commit**

```bash
git add search-ui/src/App.jsx
git commit -m "feat: rail/drawer orchestration, EXPLORE default with auto-run, graceful empty"
```

---

## Task 12: Cohesive minimal visual refresh

**Files:**
- Modify: `search-ui/src/styles.css`

**Interfaces:**
- Styles every new component (rail, drawer, range slider, presets, subcodes, active-filters, explore button) and refreshes the global palette/spacing/cards.

- [ ] **Step 1: Replace `styles.css`**

Replace the contents of `search-ui/src/styles.css` with:

```css
:root {
  --ink: #14181f; --muted: #687280; --line: #eceef2; --bg: #fafbfc;
  --accent: #2563a8; --accent-soft: #eaf1fa; --chip: #f1f3f6; --ok: #1f7a4d;
  --radius: 12px; --shadow: 0 6px 24px rgba(20,24,31,.08);
}
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: var(--ink); background: var(--bg); }
.wrap { max-width: 980px; margin: 0 auto; padding: 0 18px; }
header { background: #fff; border-bottom: 1px solid var(--line); padding: 20px 0; position: sticky; top: 0; z-index: 5; }
h1 { margin: 0 0 2px; font-size: 19px; letter-spacing: -.3px; }
.sub { color: var(--muted); font-size: 13px; }
form { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
input[type=search] { flex: 1 1 320px; min-width: 200px; padding: 11px 14px; border: 1px solid var(--line); border-radius: 10px; font-size: 15px; background: #fff; }
input[type=search]:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
select, button { padding: 11px 14px; border: 1px solid var(--line); border-radius: 10px; background: #fff; font-size: 14px; }
button { background: var(--accent); color: #fff; border-color: var(--accent); cursor: pointer; font-weight: 600; }
button:disabled { opacity: .55; cursor: default; }
.explore-btn { background: #fff; color: var(--accent); }
main { padding: 22px 0 64px; }
.layout { display: flex; gap: 20px; align-items: flex-start; position: relative; }
.results { flex: 1 1 auto; min-width: 0; }

.meta { color: var(--muted); font-size: 13px; margin: 4px 2px 14px; }
.card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; margin-bottom: 12px; }
.card h2 { margin: 0 0 6px; font-size: 16px; line-height: 1.35; }
.card h2 a { color: var(--accent); text-decoration: none; }
.card h2 a:hover { text-decoration: underline; }
.badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); text-transform: uppercase; letter-spacing: .3px; }
.badge.estado { background: #eaf6ef; color: var(--ok); }
.row { color: var(--muted); font-size: 13.5px; margin: 2px 0; }
.row b { color: var(--ink); font-weight: 600; }
.money { display: flex; gap: 14px; flex-wrap: wrap; margin: 6px 0; font-size: 13.5px; }
.money b { color: var(--ink); }
.chips { display: flex; gap: 5px; flex-wrap: wrap; margin: 8px 0 2px; }
.chip { font-size: 12px; background: var(--chip); color: #44506a; padding: 3px 9px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; }
.chip button { padding: 0; margin: 0; border: none; background: none; color: #8893a4; cursor: pointer; font-size: 12px; font-weight: 700; }
.chip .hint { color: var(--accent); font-style: normal; font-size: 11px; }
.chip .drill { color: var(--accent); }
.snippet { color: #46566c; font-size: 13px; margin-top: 8px; max-height: 3.1em; overflow: hidden; }
.score { float: right; color: #9aa7b8; font-size: 12px; font-variant-numeric: tabular-nums; }
.empty { color: var(--muted); text-align: center; padding: 44px 0; }
.err { background: #fdecec; border: 1px solid #f5c2c2; color: #9b2226; padding: 10px 12px; border-radius: 10px; margin: 8px 0; }
.more { margin: 16px auto; display: block; background: #fff; color: var(--accent); }

/* Active filters */
.active-filters { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 0 0 14px; }
.active-filters .clear-all { background: none; border: none; color: var(--muted); font-weight: 600; padding: 2px 6px; }

/* Bookmark rail */
.filter-rail { position: sticky; top: 92px; flex: 0 0 auto; display: flex; flex-direction: column; gap: 6px; }
.rail-tab { background: #fff; color: var(--ink); border: 1px solid var(--line); border-right: none; border-radius: 10px 0 0 10px; padding: 10px 12px; font-size: 13px; font-weight: 600; text-align: left; min-width: 116px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.rail-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); box-shadow: var(--shadow); }
.rail-badge { background: var(--accent-soft); color: var(--accent); border-radius: 999px; font-size: 11px; padding: 0 6px; min-width: 18px; text-align: center; }
.rail-tab.active .rail-badge { background: #fff; color: var(--accent); }

/* Drawer */
.filter-drawer { position: absolute; top: 0; right: 124px; width: 320px; max-width: 88vw; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); z-index: 10; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--line); font-weight: 600; }
.drawer-head button { background: none; border: none; color: var(--muted); }
.drawer-body { padding: 14px; max-height: 60vh; overflow: auto; }

/* Checks / selects shared */
.checks { display: flex; flex-direction: column; gap: 6px; max-height: 260px; overflow: auto; }
.check { display: flex; gap: 7px; align-items: center; font-size: 14px; }
.cpv-select input, .budget-range input { width: 100%; }
.cpv-suggestions { list-style: none; margin: 6px 0; padding: 0; max-height: 240px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
.cpv-suggestions li, .cpv-subcodes li { padding: 7px 9px; cursor: pointer; font-size: 13px; }
.cpv-suggestions li:hover, .cpv-subcodes li:hover { background: var(--accent-soft); }
.cpv-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.cpv-path { font-size: 12px; color: var(--muted); }
.cpv-chips { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.cpv-subcodes { list-style: none; margin: 4px 0 4px 12px; padding: 0; border-left: 2px solid var(--line); }

/* Range slider */
.range-slider { position: relative; height: 30px; margin: 14px 4px; }
.range-track { position: absolute; top: 13px; left: 0; right: 0; height: 4px; background: var(--line); border-radius: 4px; }
.range-fill { position: absolute; top: 13px; height: 4px; background: var(--accent); border-radius: 4px; }
.range-thumb { position: absolute; top: 0; left: 0; width: 100%; margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
.range-thumb::-webkit-slider-thumb { pointer-events: auto; -webkit-appearance: none; height: 18px; width: 18px; border-radius: 50%; background: #fff; border: 2px solid var(--accent); cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.2); }
.range-thumb::-moz-range-thumb { pointer-events: auto; height: 18px; width: 18px; border-radius: 50%; background: #fff; border: 2px solid var(--accent); cursor: pointer; }
.range-inputs { display: flex; gap: 10px; }
.range-inputs label { flex: 1; font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 3px; }
.range-caption { font-size: 12px; color: var(--muted); margin: 2px 0 8px; }
.presets { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 4px; }
.preset { background: var(--chip); color: var(--ink); border: none; font-size: 12px; font-weight: 600; padding: 5px 10px; border-radius: 999px; }
.open-toggle { margin-top: 10px; }

@media (max-width: 800px) {
  .layout { flex-direction: column; }
  .filter-rail { position: static; flex-direction: row; flex-wrap: wrap; order: -1; }
  .rail-tab { border-radius: 10px; border-right: 1px solid var(--line); min-width: auto; }
  .filter-drawer { position: static; right: auto; width: 100%; margin-bottom: 12px; }
}
```

- [ ] **Step 2: Verify build and full test suite**

Run: `cd search-ui && npm run build && npm test`
Expected: build succeeds; all suites pass.

- [ ] **Step 3: Manual smoke test**

Run `cd search-ui && npm run dev` against the API and verify: app loads straight into EXPLORE results (PUB+PRE, latest); rail tabs open/close a drawer (re-click, outside-click, Esc); CPV typeahead + subcode drill-down replaces the chip; budget log-slider + numeric inputs sync; date presets + timeline + "open only" work; "Explorar" re-applies the preset; "Limpiar" empties to the idle prompt; "Cargar más" paginates; result cards show CPV/NUTS labels.

- [ ] **Step 4: Commit**

```bash
git add search-ui/src/styles.css
git commit -m "feat: cohesive minimal visual refresh + styles for rail/drawer/sliders"
```

---

## Deployment note (not a code task)

The empty-query "error" the user saw is most likely the **deployed** search-api predating browse mode (commit `b7004c5`) and rejecting empty `q` with HTTP 422. After this UI lands, verify the deployed API:
`curl ".../api/search?cpv=45&k=3"` should return browse results (not 422). If it 422s, deploy the current `search-api/` before the new UI's default EXPLORE view will work.

## Self-Review Notes

- **Spec coverage:** rail+drawer → Tasks 9/11; active-filter chips + clear → Tasks 2/10/11; CPV drill-down → Tasks 1/8; RangeSlider/BudgetRange/DateTimeline → Tasks 3/4/5/6; MultiCheck → Task 7; EXPLORE preset + default-on-load auto-run → Tasks 2/11; empty/error handling → Task 11; visual refresh → Task 12; deployment → note. All §2–§10 covered.
- **Type consistency:** `filtersToParams`/`activeFilterList`/`EMPTY`/`EXPLORE`/`presetRange`/`budgetToPos`/`posToBudget` signatures match between Tasks 2/3 and consumers (5/6/10/11); `cpvChildren` matches between Tasks 1 and 8; `RangeSlider` `value`/`onChange`/`scale` props match between Tasks 4 and 5/6; `FilterRail`/`FilterDrawer`/`ActiveFilters`/`MultiCheck` props match between their tasks and Task 11.
- **No placeholders:** every code step contains full implementation.
```
