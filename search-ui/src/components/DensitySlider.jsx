import { useId, useRef, useState, useEffect, useCallback } from 'react'
import { densityPath } from '../density.js'

const W = 1000, H = 48

/**
 * DensitySlider — dual-handle range slider with a density sparkline backdrop.
 *
 * Props:
 *   min, max       — raw domain bounds (e.g. 1000, 100_000_000 for budget)
 *   low, high      — current selected raw values (controlled)
 *   density        — array of count numbers (one per bucket)
 *   format         — (rawValue) => string for labels
 *   toPos          — (rawValue, min, max) => 0..1  (defaults to linear)
 *   toValue        — (pos 0..1, min, max) => rawValue (defaults to linear)
 *   onChange       — ({ low, high }) called on each pointer move
 */
export default function DensitySlider({
  min, max, low, high, density = [], onChange,
  format = (v) => v,
  toPos = (v, lo, hi) => hi <= lo ? 0 : Math.max(0, Math.min(1, (v - lo) / (hi - lo))),
  toValue = (p, lo, hi) => lo + Math.max(0, Math.min(1, p)) * (hi - lo),
  ticks = [],
  loading = false,
}) {
  const uid = useId()
  const trackRef = useRef(null)
  const [dragging, setDragging] = useState(null) // 'low' | 'high' | null

  const lowPos  = toPos(low,  min, max)
  const highPos = toPos(high, min, max)
  const d = densityPath(density, W, H)

  // Compute position fraction from pointer event
  const fracFromEvent = useCallback((e) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect) return null
    const clientX = e.touches ? e.touches[0].clientX : e.clientX
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  }, [])

  const handlePointerMove = useCallback((e) => {
    if (!dragging) return
    const frac = fracFromEvent(e)
    if (frac == null) return
    const raw = Math.round(toValue(frac, min, max))
    if (dragging === 'low')  onChange({ low: Math.min(raw, high),  high })
    if (dragging === 'high') onChange({ low, high: Math.max(raw, low) })
  }, [dragging, fracFromEvent, toValue, min, max, low, high, onChange])

  const handlePointerUp = useCallback(() => setDragging(null), [])

  useEffect(() => {
    if (!dragging) return
    window.addEventListener('mousemove', handlePointerMove)
    window.addEventListener('touchmove', handlePointerMove, { passive: false })
    window.addEventListener('mouseup', handlePointerUp)
    window.addEventListener('touchend', handlePointerUp)
    return () => {
      window.removeEventListener('mousemove', handlePointerMove)
      window.removeEventListener('touchmove', handlePointerMove)
      window.removeEventListener('mouseup', handlePointerUp)
      window.removeEventListener('touchend', handlePointerUp)
    }
  }, [dragging, handlePointerMove, handlePointerUp])

  const startDrag = (which, e) => {
    e.preventDefault()
    setDragging(which)
  }

  return (
    <div className="density-slider">
      {loading && <span className="ds-loading-dot" aria-hidden="true" />}
      {/* Sparkline */}
      <svg className="density-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        {/* Unselected dimmed area */}
        <path d={d} className="density-area density-area-dim" />
        {/* Selected (highlighted) area clipped between low/high */}
        <clipPath id={`ds-sel-${uid}`}>
          <rect x={`${lowPos * 100}%`} width={`${(highPos - lowPos) * 100}%`} y="0" height={H} />
        </clipPath>
        <path d={d} className="density-area density-area-sel" clipPath={`url(#ds-sel-${uid})`} />
      </svg>

      {/* Track */}
      <div className="ds-track" ref={trackRef}>
        <div className="ds-fill"
          style={{ left: `${lowPos * 100}%`, right: `${(1 - highPos) * 100}%` }} />

        {/* Low thumb */}
        <div
          className="ds-thumb-handle"
          style={{ left: `${lowPos * 100}%` }}
          onMouseDown={(e) => startDrag('low', e)}
          onTouchStart={(e) => startDrag('low', e)}
          role="slider" aria-label="Mínimo"
          aria-valuenow={low} aria-valuemin={min} aria-valuemax={max}
          tabIndex={0}
          onKeyDown={(e) => {
            const step = (max - min) / 100
            if (e.key === 'ArrowRight') onChange({ low: Math.min(low + step, high), high })
            if (e.key === 'ArrowLeft')  onChange({ low: Math.max(low - step, min), high })
          }}
        />

        {/* High thumb */}
        <div
          className="ds-thumb-handle"
          style={{ left: `${highPos * 100}%` }}
          onMouseDown={(e) => startDrag('high', e)}
          onTouchStart={(e) => startDrag('high', e)}
          role="slider" aria-label="Máximo"
          aria-valuenow={high} aria-valuemin={min} aria-valuemax={max}
          tabIndex={0}
          onKeyDown={(e) => {
            const step = (max - min) / 100
            if (e.key === 'ArrowRight') onChange({ low, high: Math.min(high + step, max) })
            if (e.key === 'ArrowLeft')  onChange({ low, high: Math.max(high - step, low) })
          }}
        />
      </div>

      {ticks.length > 0 && (
        <div className="ds-ticks" aria-hidden="true">
          {ticks.map(({ pos, label }) => (
            <span key={label} className="ds-tick" style={{ left: `${pos * 100}%` }}>
              <span className="ds-tick-mark" />
              <span className="ds-tick-lbl">{label}</span>
            </span>
          ))}
        </div>
      )}

      <div className="ds-labels">
        <span className="ds-val">{format(low)}</span>
        <span className="ds-val">{format(high)}</span>
      </div>
    </div>
  )
}
