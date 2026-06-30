import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { Tray, SignOut, User } from '../icons.js'

export default function UserMenu({ onOpenSaved, onOpenProfile }) {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  if (!user) return null

  const initial = (user.display_name || user.email || '?')[0].toUpperCase()

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="user-trigger"
        onClick={() => setOpen(!open)}
      >
        <span className="user-avatar">{initial}</span>
        <span className="user-name">{user.display_name || user.email}</span>
      </button>

      {open && (
        <div className="user-dropdown">
          <button
            type="button"
            onClick={() => { setOpen(false); onOpenProfile?.() }}
          >
            <User size={16} /> Mi Perfil
          </button>
          <button
            type="button"
            onClick={() => { setOpen(false); onOpenSaved?.() }}
          >
            <Tray size={16} /> Mi Espacio
          </button>
          <hr />
          <button
            type="button"
            onClick={() => { setOpen(false); logout() }}
          >
            <SignOut size={16} /> Cerrar sesión
          </button>
        </div>
      )}
    </div>
  )
}
