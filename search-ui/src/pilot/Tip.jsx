// search-ui/src/pilot/Tip.jsx — a short explanation on hover (or focus), in a card fixed to the
// window so a scrolling panel never clips it.
import { useRef, useState } from 'react'

const W = 260

export default function Tip({ tip, children, className = '' }) {
  const el = useRef(null)
  const [pos, setPos] = useState(null)
  if (!tip) return children
  const show = () => {
    const r = el.current.getBoundingClientRect()
    const below = window.innerHeight - r.bottom > 90
    setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)),
      ...(below ? { top: r.bottom + 6 } : { bottom: window.innerHeight - r.top + 6 }) })
  }
  return (
    <span ref={el} className={`tip ${className}`} tabIndex={0} onMouseEnter={show} onMouseLeave={() => setPos(null)} onFocus={show} onBlur={() => setPos(null)}>
      {children}
      {pos && <span className="tip-card" role="tooltip" style={{ ...pos, maxWidth: W }}>{tip}</span>}
    </span>
  )
}
