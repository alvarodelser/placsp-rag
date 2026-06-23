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
