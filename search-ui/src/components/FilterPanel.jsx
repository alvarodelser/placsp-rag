import statusMap from '../codelists/status.json'
import resultMap from '../codelists/result.json'
import typeMap from '../codelists/contract_type.json'
import procMap from '../codelists/procedure.json'
import CpvSelect from './CpvSelect.jsx'
import NutsSelect from './NutsSelect.jsx'

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

      <fieldset className="filter-group">
        <legend>Ubicación (NUTS)</legend>
        <NutsSelect value={filters.nuts} onChange={(nuts) => set({ nuts })} />
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
