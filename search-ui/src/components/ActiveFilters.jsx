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
  if (field === 'deadline') return `Plazo: ${value}`
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
