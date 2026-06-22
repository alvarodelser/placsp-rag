import { useState } from 'react'
import { search } from './api.js'
import ResultCard from './components/ResultCard.jsx'

const MODES = [
  ['hybrid', 'Híbrida'],
  ['vector', 'Semántica'],
  ['keyword', 'Palabra clave'],
]

export default function App() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [state, setState] = useState({ status: 'idle' }) // idle | loading | done | error

  async function onSubmit(e) {
    e.preventDefault()
    const query = q.trim()
    if (!query) return
    setState({ status: 'loading' })
    try {
      const data = await search(query, mode, 15)
      setState({ status: 'done', data })
    } catch (err) {
      setState({ status: 'error', message: err.message })
    }
  }

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda semántica y por palabra clave</div>
          <form onSubmit={onSubmit}>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza de edificios públicos"
              autoFocus
            />
            <select value={mode} onChange={(e) => setMode(e.target.value)} title="Modo de búsqueda">
              {MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : 'Buscar'}
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap">
          {state.status === 'error' && <div className="err">Error: {state.message}</div>}

          {state.status === 'done' && (
            <>
              <div className="meta">{state.data.count} resultado(s) · modo {state.data.mode}</div>
              {state.data.errors && (
                <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>
              )}
              {state.data.results.length > 0 ? (
                state.data.results.map((r) => <ResultCard key={r._id || r.syndication_id} r={r} />)
              ) : (
                <div className="empty">Sin resultados.</div>
              )}
            </>
          )}

          {state.status === 'idle' && (
            <div className="empty">Escribe una consulta y pulsa Buscar.</div>
          )}
        </div>
      </main>
    </>
  )
}
