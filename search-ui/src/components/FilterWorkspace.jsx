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
import { budgetToPos, posToBudget, presetRange, presetDeadlineRange, todayISO } from '../filters.js'
import { money } from '../format.js'
import {
  Stack, MapPin, Calendar, HourglassHigh, CurrencyEur, ListChecks, Scales, Gavel, X, Trophy,
} from '../icons.js'
import { RESULT_GROUPS, TYPE_GROUPS, PROC_GROUPS } from '../facetGroups.js'

const CATS = [
  { id: 'cpv',           label: 'CPV',           Icon: Stack,         fields: ['cpv'] },
  { id: 'nuts',          label: 'Ubicación',      Icon: MapPin,        fields: ['nuts'] },
  { id: 'publicacion',   label: 'Publicación',    Icon: Calendar,      fields: ['pub_from', 'pub_to'] },
  { id: 'presentacion',  label: 'Presentación',   Icon: HourglassHigh, fields: ['deadline_from', 'deadline_to'] },
  { id: 'budget',        label: 'Presupuesto',    Icon: CurrencyEur,   fields: ['budget_min', 'budget_max'] },
  { id: 'status',        label: 'Estado',         Icon: ListChecks,    fields: ['status'] },
  { id: 'result',        label: 'Resultado',      Icon: Trophy,        fields: ['result'] },
  { id: 'contract_type', label: 'Tipo',           Icon: Scales,        fields: ['contract_type'] },
  { id: 'procedure',     label: 'Procedimiento',  Icon: Gavel,         fields: ['procedure'] },
]

function catCount(cat, f) {
  if (['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure'].includes(cat.id))
    return (f[cat.id] || []).length
  if (cat.id === 'publicacion')  return (f.pub_from || f.pub_to) ? 1 : 0
  if (cat.id === 'presentacion') return (f.deadline_from || f.deadline_to) ? 1 : 0
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

function next18Months() {
  const out = []
  const now = new Date()
  for (let i = 0; i <= 17; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1)
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  return out
}
const STATIC_FUTURE_MONTHS = next18Months()

function useLazyTab(active, tabId, filters, fetcher) {
  const tabIds = Array.isArray(tabId) ? tabId : [tabId]
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const keyRef = useRef(null)
  useEffect(() => {
    if (!tabIds.includes(active)) return
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

  const { data: locationData,  loading: locationLoading }  = useLazyTab(active, 'nuts',          filters, locationDist)
  const { data: statusData,    loading: statusLoading }    = useLazyTab(active, 'status',        filters, statusDist)
  const { data: resultData,    loading: resultLoading }    = useLazyTab(active, 'result',        filters, resultDist)
  const { data: typeData,      loading: typeLoading }      = useLazyTab(active, 'contract_type', filters, typeDist)
  const { data: procedureData, loading: procedureLoading } = useLazyTab(active, 'procedure',     filters, procedureDist)
  const { data: budgetData,    loading: budgetLoading }    = useLazyTab(active, 'budget',        filters, budgetDist)
  const { data: datesData,     loading: datesLoading }     = useLazyTab(active, ['publicacion', 'presentacion'], filters, datesDist)

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

      case 'publicacion': {
        const loadedSeries = datesData?.dates?.publication || []
        const months  = loadedSeries.length > 0 ? loadedSeries.map(s => s.month) : STATIC_MONTHS
        const density = loadedSeries.length > 0 ? loadedSeries.map(s => s.count) : []
        const n = Math.max(0, months.length - 1)
        const currentFrom = filters.pub_from ? filters.pub_from.slice(0, 7) : null
        const currentTo   = filters.pub_to   ? filters.pub_to.slice(0, 7)   : null
        const loIdx = currentFrom ? Math.max(0, months.indexOf(currentFrom)) : 0
        const hiIdx = currentTo   ? Math.max(0, months.indexOf(currentTo))   : n
        return (
          <div className="dates-filter">
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
                  patch({ pub_from: from ? `${from}-01` : '', pub_to: to ? `${to}-28` : '' })
                }}
              />
            </div>
            <div className="presets">
              {['month', 'quarter', 'year', 'all'].map((p) => (
                <button key={p} className="preset" onClick={() => patch(presetRange(p))}>
                  {{ month: 'Último mes', quarter: '3 meses', year: 'Año', all: 'Todo' }[p]}
                </button>
              ))}
            </div>
          </div>
        )
      }

      case 'presentacion': {
        const thisMonth = todayISO().slice(0, 7)
        const loadedSeries = (datesData?.dates?.plazo || []).filter(s => s.month >= thisMonth)
        const months  = loadedSeries.length > 0 ? loadedSeries.map(s => s.month) : STATIC_FUTURE_MONTHS
        const density = loadedSeries.length > 0 ? loadedSeries.map(s => s.count) : []
        const n = Math.max(0, months.length - 1)
        const currentFrom = filters.deadline_from ? filters.deadline_from.slice(0, 7) : null
        const currentTo   = filters.deadline_to   ? filters.deadline_to.slice(0, 7)   : null
        const loIdx = currentFrom ? Math.max(0, months.indexOf(currentFrom)) : 0
        const hiIdx = currentTo   ? Math.max(0, months.indexOf(currentTo))   : n
        return (
          <div className="dates-filter">
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
                  patch({ deadline_from: from ? `${from}-01` : '', deadline_to: to ? `${to}-28` : '' })
                }}
              />
            </div>
            <div className="presets">
              {['week', 'month', 'quarter', 'all'].map((p) => (
                <button key={p} className="preset" onClick={() => patch(presetDeadlineRange(p))}>
                  {{ week: '1 semana', month: '1 mes', quarter: '3 meses', all: 'Todo' }[p]}
                </button>
              ))}
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
