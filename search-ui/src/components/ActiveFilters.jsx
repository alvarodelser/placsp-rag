import { useState } from 'react'
import { activeFilterList } from '../filters.js'
import { GROUPS_BY_FIELD } from '../facetGroups.js'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import statusMap from '../codelists/status.json'

// Grouped facets (result, contract_type, procedure) are labelled by their
// group, not by per-code codelists — see facetGroups.js.
const MAPS = {
  cpv: cpvMap, nuts: nutsMap, status: statusMap,
}

const CAT_LABELS = {
  status: 'Estado', cpv: 'CPV', nuts: 'Ubicación',
  contract_type: 'Tipo', procedure: 'Procedimiento', result: 'Resultado',
  dates: 'Publicación', deadline: 'Presentación', budget: 'Presupuesto',
}

const CAT_ORDER = ['status', 'cpv', 'nuts', 'contract_type', 'procedure', 'result', 'dates', 'deadline', 'budget']

function labelFor({ field, value, label }) {
  if (label != null) return label
  const m = MAPS[field]
  if (m) return m[value] || value
  return value
}

const LIMIT = 3

function CategoryGroup({ label, items, onRemove }) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, LIMIT)
  const extra = items.length - LIMIT

  return (
    <div className="af-group">
      <span className="af-cat">{label}</span>
      <div className="af-items">
        {visible.map((e) => (
          <span className="af-chip" key={`${e.field}:${e.value}`}>
            {labelFor(e)}
            <button type="button" aria-label="Quitar" onClick={() => onRemove(e.field, e.value)}>✕</button>
          </span>
        ))}
        {!expanded && extra > 0 && (
          <button type="button" className="af-more" onClick={() => setExpanded(true)}>{extra} más…</button>
        )}
        {expanded && extra > 0 && (
          <button type="button" className="af-more" onClick={() => setExpanded(false)}>Menos</button>
        )}
      </div>
    </div>
  )
}

export default function ActiveFilters({ filters, onRemove }) {
  const list = activeFilterList(filters)
  if (list.length === 0) return null

  const groups = {}
  for (const e of list) {
    if (GROUPS_BY_FIELD[e.field]) continue // grouped facets collapsed below
    if (!groups[e.field]) groups[e.field] = []
    groups[e.field].push(e)
  }

  // Collapse grouped facets: one chip per group that has any code selected;
  // its value is the whole code set, so removing it clears all of them.
  for (const field of Object.keys(GROUPS_BY_FIELD)) {
    const sel = filters[field] || []
    if (sel.length === 0) continue
    const items = GROUPS_BY_FIELD[field]
      .filter((g) => g.codes.some((c) => sel.includes(c)))
      .map((g) => ({ field, value: g.codes, label: g.label }))
    if (items.length) groups[field] = items
  }

  return (
    <div className="active-filters">
      {CAT_ORDER.filter((cat) => groups[cat]?.length > 0).map((cat) => (
        <CategoryGroup key={cat} label={CAT_LABELS[cat]} items={groups[cat]} onRemove={onRemove} />
      ))}
    </div>
  )
}
