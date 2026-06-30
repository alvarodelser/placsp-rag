import { useState } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { CircleNotch, EnvelopeSimple, Lock, User, Eye, EyeSlash } from '../icons.js'

export default function AuthPage() {
  const { login, register } = useAuth()
  const [tab, setTab] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (!email.trim() || !email.includes('@')) {
      setError('Introduce un email válido')
      return
    }
    if (password.length < 8) {
      setError('La contraseña debe tener al menos 8 caracteres')
      return
    }
    if (tab === 'register') {
      if (!displayName.trim()) {
        setError('El nombre es obligatorio')
        return
      }
      if (password !== confirmPw) {
        setError('Las contraseñas no coinciden')
        return
      }
    }

    setLoading(true)
    try {
      if (tab === 'login') {
        await login(email.trim(), password)
      } else {
        await register({ email: email.trim(), password, display_name: displayName.trim() })
      }
    } catch (err) {
      setError(err.message || 'Error inesperado')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <h1>PLACSP</h1>
          <p>Contratación del sector público</p>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab${tab === 'login' ? ' active' : ''}`}
            onClick={() => { setTab('login'); setError('') }}
          >
            Iniciar sesión
          </button>
          <button
            type="button"
            className={`auth-tab${tab === 'register' ? ' active' : ''}`}
            onClick={() => { setTab('register'); setError('') }}
          >
            Crear cuenta
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {tab === 'register' && (
            <div className="auth-field">
              <User size={18} className="auth-icon" />
              <input
                type="text"
                placeholder="Nombre"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}

          <div className="auth-field">
            <EnvelopeSimple size={18} className="auth-icon" />
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
            />
          </div>

          <div className="auth-field">
            <Lock size={18} className="auth-icon" />
            <input
              type={showPw ? 'text' : 'password'}
              placeholder="Contraseña"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
            />
            <button
              type="button"
              className="auth-toggle-pw"
              onClick={() => setShowPw(!showPw)}
              tabIndex={-1}
            >
              {showPw ? <EyeSlash size={16} /> : <Eye size={16} />}
            </button>
          </div>

          {tab === 'register' && (
            <div className="auth-field">
              <Lock size={18} className="auth-icon" />
              <input
                type={showPw ? 'text' : 'password'}
                placeholder="Repetir contraseña"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                autoComplete="new-password"
              />
            </div>
          )}

          {error && <div className="auth-error">{error}</div>}

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading
              ? <><CircleNotch size={18} className="spinner" /> Cargando…</>
              : tab === 'login' ? 'Entrar' : 'Crear cuenta'}
          </button>
        </form>
      </div>
    </div>
  )
}
