import { useState } from 'react'
import CpvMiller from './CpvMiller.jsx'
import SpainMap from './SpainMap.jsx'
import DensitySlider from './DensitySlider.jsx'
import StatusDiagram from './StatusLifecycle.jsx'
import MultiCheckIcons from './MultiCheckIcons.jsx'
import LiveResults from './LiveResults.jsx'
import { budgetToPos, posToBudget, presetRange, todayISO } from '../filters.js'
import { money } from '../format.js'
import {
  Stack, MapPin, Calendar, CurrencyEur, ListChecks, Scales, Gavel, X,
  Package, Wrench, HandCoins, Storefront, FileText, ArrowsLeftRight, UsersThree,
  CheckCircle, XCircle, HourglassHigh,
} from '../icons.js'
import typeMap from '../codelists/contract_type.json'
import procMap from '../codelists/procedure.json'

// Icon maps for contract types
const TYPE_ICONS = {
  '1':  Package,          // Suministros
  '2':  FileText,         // Servicios
  '21': Storefront,       // Gestión de Servicios Públicos
  '22': HandCoins,        // Concesión de Servicios
  '3':  Wrench,           // Obras
  '31': Wrench,           // Concesión de Obras Públicas
  '32': Wrench,           // Concesión de Obras
  '40': UsersThree,       // Colaboración P-P
  '50': FileText,         // Patrimonial
  '7':  FileText,         // Administrativo especial
  '8':  FileText,         // Privado
}

// Icon maps for procedures
const PROC_ICONS = {
  '1':   ArrowsLeftRight, // Abierto
  '9':   ArrowsLeftRight, // Abierto simplificado
  '2':   ListChecks,      // Restringido
  '3':   Gavel,           // Negociado sin publicidad
  '4':   Gavel,           // Negociado con publicidad
  '5':   UsersThree,      // Diálogo competitivo
  '6':   FileText,        // Contrato menor
  '7':   ArrowsLeftRight, // Derivado de acuerdo marco
  '8':   Scales,          // Concurso de proyectos
  '10':  UsersThree,      // Asociación para la innovación
  '11':  ArrowsLeftRight, // Derivado de asociación
  '12':  ArrowsLeftRight, // Basado en SDA
  '13':  Gavel,           // Licitación con negociación
  '100': FileText,        // Normas internas
  '999': FileText,        // Otros
}

const CATS = [
  { id: 'cpv',           label: 'CPV',          Icon: Stack,        fields: ['cpv'] },
  { id: 'nuts',          label: 'Ubicación',     Icon: MapPin,       fields: ['nuts'] },
  { id: 'dates',         label: 'Fechas',        Icon: Calendar,     fields: ['pub_from', 'pub_to', 'deadline_from'] },
  { id: 'budget',        label: 'Presupuesto',   Icon: CurrencyEur,  fields: ['budget_min', 'budget_max'] },
  { id: 'status',        label: 'Estado',        Icon: ListChecks,   fields: ['status'] },
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

export default function FilterWorkspace({ filters, patch, setList, facetsData, total, previewResults, loading, onClose }) {
  const [active, setActive] = useState('cpv')
  const [dateAxis, setDateAxis] = useState('publication')

  const center = () => {
    switch (active) {
      case 'cpv':
        return <CpvMiller value={filters.cpv} onChange={(v) => setList('cpv', v)} />

      case 'nuts':
        return (
          <SpainMap
            value={filters.nuts}
            counts={facetsData?.nuts || {}}
            onChange={(v) => setList('nuts', v)}
          />
        )

      case 'status':
        return (
          <StatusDiagram
            value={filters.status}
            counts={facetsData?.status || {}}
            onChange={(v) => setList('status', v)}
          />
        )

      case 'contract_type':
        return (
          <MultiCheckIcons
            map={typeMap}
            value={filters.contract_type}
            onChange={(v) => setList('contract_type', v)}
            icons={TYPE_ICONS}
            counts={facetsData?.contract_type || {}}
          />
        )

      case 'procedure':
        return (
          <MultiCheckIcons
            map={procMap}
            value={filters.procedure}
            onChange={(v) => setList('procedure', v)}
            icons={PROC_ICONS}
            counts={facetsData?.procedure || {}}
          />
        )

      case 'budget': {
        const lo = Number(filters.budget_min) || 1000
        const hi = Number(filters.budget_max) || 100000000
        return (
          <DensitySlider
            min={1000} max={100000000}
            low={lo} high={hi}
            density={(facetsData?.budget || []).map((b) => b.count)}
            toPos={budgetToPos}
            toValue={posToBudget}
            format={(v) => money(v)}
            onChange={({ low, high }) => patch({ budget_min: String(low), budget_max: String(high) })}
          />
        )
      }

      case 'dates': {
        const series = (facetsData?.dates?.[dateAxis] || [])
        const months = series.map((s) => s.month)
        const n = Math.max(0, months.length - 1)

        // Map current filter dates to slider indices
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
            {months.length > 1 ? (
              <DensitySlider
                min={0} max={n}
                low={loIdx} high={hiIdx < 0 ? n : hiIdx}
                density={series.map((s) => s.count)}
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
            ) : (
              <div className="ds-empty">Cargando datos de fechas…</div>
            )}
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
