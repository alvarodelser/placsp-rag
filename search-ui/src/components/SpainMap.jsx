import { useMemo, useState } from 'react'
import { geoMercator, geoPath } from 'd3-geo'
import nuts2 from '../geo/spain-nuts2.json'
import nuts3 from '../geo/spain-nuts3.json'
import { aggregateByLevel } from '../geo/nuts.js'

const W = 460, H = 360

function shade(n, max) {
  if (!n) return 'var(--bg)'
  const t = Math.min(1, Math.log(n + 1) / Math.log(max + 1))
  const steps = ['#eef2f7', '#cfe0f3', '#9cc1e8', '#5b94d6', '#2f6fc0']
  return steps[Math.min(steps.length - 1, Math.floor(t * steps.length))]
}

export default function SpainMap({ value, counts, onChange }) {
  const [level, setLevel] = useState(2)
  const fc = level === 2 ? nuts2 : nuts3
  const byLevel = useMemo(() => aggregateByLevel(counts || {}, level), [counts, level])
  const max = Math.max(1, ...Object.values(byLevel))

  const path = useMemo(() => {
    const proj = geoMercator().fitSize([W, H], fc)
    return geoPath(proj)
  }, [fc])

  const toggle = (id) => onChange(
    value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <div className="spain-map">
      <div className="sm-toggle">
        <button type="button" className={level === 2 ? 'on' : ''} onClick={() => setLevel(2)}>Comunidades</button>
        <button type="button" className={level === 3 ? 'on' : ''} onClick={() => setLevel(3)}>Provincias</button>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="sm-svg">
        {fc.features.map((f) => {
          const d = path(f)
          if (!d) return null
          return (
            <path key={f.id} d={d}
              className={`sm-region${value.includes(f.id) ? ' sel' : ''}`}
              fill={shade(byLevel[f.id], max)}
              onClick={() => toggle(f.id)}>
              <title>{f.properties.name} · {byLevel[f.id] || 0}</title>
            </path>
          )
        })}
      </svg>
      <div className="sm-list">
        {value.map((id) => {
          const f = fc.features.find((x) => x.id === id)
          return <span className="chip" key={id}>{f ? f.properties.name : id}
            <button type="button" aria-label="Quitar" onClick={() => toggle(id)}>✕</button></span>
        })}
      </div>
    </div>
  )
}
