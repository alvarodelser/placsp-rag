import { useState, useEffect, useRef } from 'react'
import {
  budgetDist, datesDist, locationDist,
  statusDist, resultDist, typeDist, procedureDist,
} from '../api.js'
import { filtersToParams } from '../filters.js'
import CpvMiller from './CpvMiller.jsx'
import SpainMap from './SpainMap.jsx'
import DensitySlider from './DensitySlider.jsx'
import StatusDiagram from './StatusLifecycle.jsx'
import GroupedFacet from './GroupedFacet.jsx'
import ProcedureAxis from './ProcedureAxis.jsx'
import { budgetToPos, posToBudget, presetRange, todayISO } from '../filters.js'
import { money } from '../format.js'
import {
  Stack, MapPin, Calendar, CurrencyEur, ListChecks, Scales, Gavel, X, Trophy,
} from '../icons.js'
import { RESULT_GROUPS, TYPE_GROUPS, PROC_GROUPS } from '../facetGroups.js'

const CATS = [
  { id: 'cpv',           label: 'CPV',          Icon: Stack,        fields: ['cpv'] },
  { id: 'nuts',          label: 'Ubicación',     Icon: MapPin,       fields: ['nuts'] },
  { id: 'dates',         label: 'Fechas',        Icon: Calendar,     fields: ['pub_from', 'pub_to', 'deadline_from'] },
  { id: 'budget',        label: 'Presupuesto',   Icon: CurrencyEur,  fields: ['budget_min', 'budget_max'] },
  { id: 'status',        label: 'Estado',        Icon: ListChecks,   fields: ['status'] },
  { id: 'result',        label: 'Resultado',     Icon: Trophy,       fields: ['result'] },
  { id: 'contract_type', label: 'Tipo',          Icon: Scales,       fields: ['contract_type'] },
  { id: 'procedure',     label: 'Procedimiento', Icon: Gavel,        fields: ['procedure'] },
]

function catCount(cat, f) {
  if (['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure'].includes(cat.id))
    return (f[cat.id] || []).length
  if (cat.id === 'dates') return (f.pub_from || f.pub_to || f.deadline_from || f.deadline_to) ? 1 : 0
  if (cat.id === 'budget') return (f.budget_min || f.budget_max) ? 1 : 0
  return 0
}

function fmtTotal(n) {
  if (n == null) return null
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return n.toLocaleString('es-ES')
}

function last36Months() {
  const out = []
  const now = new Date()
  for (let i = 35; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  return out
}
const STATIC_MONTHS = last36Months()

function useLazyTab(active, tabId, filters, fetcher) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const keyRef = useRef(null)
  useEffect(() => {
    if (active !== tabId) return
    const key = JSON.stringify(filtersToParams(filters))
    if (key === keyRef.current) return
    let cancelled = false
    setLoading(true)
    fetcher(filtersToParams(filters))
      .then(d  => { if (!cancelled) { setData(d); keyRef.current = key } })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [active, filters]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, loading }
}

export default function FilterWorkspace({ filters, patch, setList, facetsData, total, previewResults, loading, onClose, onClear }) {
  const [active, setActive] = useState('cpv')
  const [dateAxis, setDateAxis] = useState('publication')

  const { data: locationData,  loading: locationLoading }  = useLazyTab(active, 'nuts',          filters, locationDist)
  const { data: statusData,    loading: statusLoading }    = useLazyTab(active, 'status',        filters, statusDist)
  const { data: resultData,    loading: resultLoading }    = useLazyTab(active, 'result',        filters, resultDist)
  const { data: typeData,      loading: typeLoading }      = useLazyTab(active, 'contract_type', filters, typeDist)
  const { data: procedureData, loading: procedureLoading } = useLazyTab(active, 'procedure',     filters, procedureDist)
  const { data: budgetData,    loading: budgetLoading }    = useLazyTab(active, 'budget',        filters, budgetDist)
  const { data: datesData,     loading: datesLoading }     = useLazyTab(active, 'dates',         filters, datesDist)

  const center = () => {
    switch (active) {
      case 'cpv':
        return (
          <CpvMiller
            value={filters.cpv}
            onChange={(v) => setList('cpv', v)}
            filterParams={filtersToParams(filters)}
          />
        )

      case 'nuts':
        return (
          <SpainMap
            value={filters.nuts}
            counts={locationData || {}}
            loading={locationLoading}
            onChange={(v) => setList('nuts', v)}
          />
        )

      case 'status':
        return (
          <StatusDiagram
            value={filters.status}
            counts={statusData || {}}
            loading={statusLoading}
            onChange={(v) => setList('status', v)}
          />
        )

      case 'result':
        return (
          <div className={resultLoading ? 'dist-loading' : ''}>
            <GroupedFacet
              groups={RESULT_GROUPS}
              value={filters.result}
              counts={resultData || {}}
              onChange={(v) => setList('result', v)}
            />
          </div>
        )

      case 'contract_type':
        return (
          <div className={typeLoading ? 'dist-loading' : ''}>
            <GroupedFacet
              groups={TYPE_GROUPS}
              value={filters.contract_type}
              counts={typeData || {}}
              onChange={(v) => setList('contract_type', v)}
            />
          </div>
        )

      case 'procedure':
        return (
          <div className={procedureLoading ? 'dist-loading' : ''}>
            <ProcedureAxis
              groups={PROC_GROUPS}
              value={filters.procedure}
              counts={procedureData || {}}
              onChange={(v) => setList('procedure', v)}
            />
          </div>
        )

      case 'budget': {
        const lo = Number(filters.budget_min) || 1000
        const hi = Number(filters.budget_max) || 100000000
        return (
          <div className={budgetLoading ? 'dist-loading' : ''}>
            <DensitySlider
              min={1000} max={100000000}
              low={lo} high={hi}
              density={(budgetData?.budget || []).map((b) => b.count)}
              toPos={budgetToPos}
              toValue={posToBudget}
              format={(v) => money(v)}
              onChange={({ low, high }) => patch({ budget_min: String(low), budget_max: String(high) })}
            />
          </div>
        )
      }

      case 'dates': {
        // Months come from loaded data when available; fall back to last 36 months
        // computed client-side so the slider is usable immediately without a DB call.
        const loadedSeries = datesData?.dates?.[dateAxis] || []
        const months  = loadedSeries.length > 0 ? loadedSeries.map(s => s.month) : STATIC_MONTHS
        const density = loadedSeries.length > 0 ? loadedSeries.map(s => s.count) : []
        const n = Math.max(0, months.length - 1)

        const fromKey = dateAxis === 'publication' ? 'pub_from' : 'deadline_from'
        const toKey   = dateAxis === 'publication' ? 'pub_to'   : 'deadline_to'
        const currentFrom = filters[fromKey] ? filters[fromKey].slice(0, 7) : null
        const currentTo   = filters[toKey]   ? filters[toKey].slice(0, 7)   : null

        const loIdx = currentFrom ? Math.max(0, months.indexOf(currentFrom)) : 0
        const hiIdx = currentTo   ? Math.max(0, months.indexOf(currentTo))   : n

        return (
          <div className="dates-filter">
            <div className="ws-axis">
              <button className={dateAxis === 'publication' ? 'on' : ''} onClick={() => setDateAxis('publication')}>Publicación</button>
              <button className={dateAxis === 'plazo' ? 'on' : ''} onClick={() => setDateAxis('plazo')}>Plazo de presentación</button>
            </div>
            <div className={datesLoading ? 'dist-loading' : ''}>
              <DensitySlider
                min={0} max={n}
                low={loIdx} high={hiIdx < 0 ? n : hiIdx}
                density={density}
                format={(i) => months[Math.round(Math.max(0, Math.min(n, i)))] || ''}
                toPos={(v, lo, hi) => hi <= lo ? 0 : Math.max(0, Math.min(1, (v - lo) / (hi - lo)))}
                toValue={(p, lo, hi) => Math.round(lo + p * (hi - lo))}
                onChange={({ low, high }) => {
                  const from = months[Math.round(low)]
                  const to   = months[Math.round(high)]
                  if (dateAxis === 'publication') patch({ pub_from: from ? `${from}-01` : '', pub_to: to ? `${to}-28` : '' })
                  else patch({ deadline_from: from ? `${from}-01` : '', deadline_to: to ? `${to}-28` : '' })
                }}
              />
            </div>
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
        </div>
        <div className="ws-foot">
          <div className="ws-foot-count">
            {facetsData?.total != null
              ? <>{fmtTotal(facetsData.total)} <span>contratos</span></>
              : <span className="ws-foot-loading">Calculando…</span>}
          </div>
          <button type="button" className="ws-clear" onClick={onClear}>Limpiar</button>
          <button type="button" className="ws-apply" onClick={onClose}>Ver resultados</button>
        </div>
      </div>
    </div>
  )
}
