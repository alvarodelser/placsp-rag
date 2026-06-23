import { useEffect, useRef } from 'react'

export default function FilterDrawer({ title, onClose, children }) {
  const ref = useRef(null)

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) onClose() }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  return (
    <div className="filter-drawer" ref={ref}>
      <div className="drawer-head">
        <span>{title}</span>
        <button type="button" onClick={onClose} aria-label="Cerrar">✕</button>
      </div>
      <div className="drawer-body">{children}</div>
    </div>
  )
}
