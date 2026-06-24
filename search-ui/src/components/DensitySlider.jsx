import { densityPath, linearPos, linearValue } from '../density.js'

const W = 1000, H = 40

export default function DensitySlider({
  min, max, low, high, density = [], onChange,
  format = (v) => v, toPos = linearPos, toValue = linearValue,
}) {
  const d = densityPath(density, W, H)
  const lowPos = toPos(low, min, max), highPos = toPos(high, min, max)
  const set = (which, pos) => {
    const v = Math.round(toValue(pos, min, max))
    onChange(which === 'low' ? { low: Math.min(v, high), high } : { low, high: Math.max(v, low) })
  }
  return (
    <div className="density-slider">
      <svg className="density-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path d={d} className="density-area" />
      </svg>
      <div className="ds-track">
        <div className="ds-fill" style={{ left: `${lowPos * 100}%`, right: `${(1 - highPos) * 100}%` }} />
        <input type="range" min="0" max="1" step="0.001" value={lowPos}
          onChange={(e) => set('low', Number(e.target.value))} className="ds-thumb" />
        <input type="range" min="0" max="1" step="0.001" value={highPos}
          onChange={(e) => set('high', Number(e.target.value))} className="ds-thumb" />
      </div>
      <div className="ds-labels"><span>{format(low)}</span><span>{format(high)}</span></div>
    </div>
  )
}
