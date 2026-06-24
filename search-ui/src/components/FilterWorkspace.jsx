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
