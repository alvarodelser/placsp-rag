import { Megaphone, HourglassHigh, CheckCircle, XCircle, Prohibit, Archive } from '../icons.js'

// Status lifecycle ordered as a pipeline of contract states
const LIFECYCLE = [
  {
    code: 'PRE',
    label: 'Anuncio Previo',
    sublabel: 'Preaviso de licitación',
    Icon: Megaphone,
    color: '#8b5cf6',
    bg: '#f3eeff',
    border: '#c4b5fd',
  },
  {
    code: 'PUB',
    label: 'En Plazo',
    sublabel: 'Abierta a ofertas',
    Icon: HourglassHigh,
    color: '#0ea5e9',
    bg: '#e0f5fe',
    border: '#7dd3fc',
  },
  {
    code: 'EV',
    label: 'Evaluación',
    sublabel: 'Pendiente de adjudicación',
    Icon: Archive,
    color: '#f59e0b',
    bg: '#fef9ec',
    border: '#fcd34d',
  },
  {
    code: 'ADJ',
    label: 'Adjudicada',
    sublabel: 'Contrato adjudicado',
    Icon: CheckCircle,
    color: '#10b981',
    bg: '#e9faf3',
    border: '#6ee7b7',
  },
  {
    code: 'RES',
    label: 'Resuelta',
    sublabel: 'Proceso concluido',
    Icon: CheckCircle,
    color: '#1f7a4d',
    bg: '#e9f7ef',
    border: '#86efac',
  },
  {
    code: 'ANUL',
    label: 'Anulada',
    sublabel: 'Proceso cancelado',
    Icon: Prohibit,
    color: '#ef4444',
    bg: '#fff1f1',
    border: '#fca5a5',
  },
]

function fmt(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`
  return String(n)
}

export default function StatusLifecycle({ value, counts = {}, onChange }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }

  return (
    <div className="lifecycle-wrap">
      <div className="lifecycle-hint">Ciclo de vida del contrato — selecciona uno o más estados</div>
      <div className="lifecycle-grid">
        {LIFECYCLE.map((s, i) => {
          const active = value.includes(s.code)
          const n = counts[s.code]
          return (
            <button
              key={s.code}
              type="button"
              className={`lifecycle-card${active ? ' on' : ''}`}
              style={{
                '--lc-color': s.color,
                '--lc-bg': active ? s.color : s.bg,
                '--lc-border': active ? s.color : s.border,
                '--lc-ink': active ? '#fff' : s.color,
              }}
              onClick={() => toggle(s.code)}
              aria-pressed={active}
            >
              {i > 0 && <div className="lifecycle-arrow" />}
              <div className="lifecycle-icon">
                <s.Icon size={22} weight={active ? 'fill' : 'regular'} />
              </div>
              <div className="lifecycle-label">{s.label}</div>
              <div className="lifecycle-sub">{s.sublabel}</div>
              {n != null && (
                <div className="lifecycle-count">{fmt(n)}</div>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
