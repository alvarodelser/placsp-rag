import { useState } from 'react'
import { search } from './api.js'
import FilterPanel from './components/FilterPanel.jsx'
import ResultCard from './components/ResultCard.jsx'

const MODES = [
  ['hybrid', 'Híbrida'],
  ['vector', 'Semántica'],
  ['keyword', 'Palabra clave'],
]

const EMPTY = {
  cpv: [], status: [], result: [], contract_type: [], procedure: [], nuts: [],
  pub_from: '', pub_to: '', deadline_from: '', deadline_to: '',
  budget_min: '', budget_max: '', sort: '',
}

const K = 15

export default function App() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [filters, setFilters] = useState(EMPTY)
  const [state, setState] = useState({ status: 'idle' }) // idle | loading | done | error

  const browse = q.trim() === ''
  // `sort` is a browse-mode ordering choice, not a filter — exclude it so
  // touching the sort selector alone doesn't trigger an empty browse request.
  const hasFilters = Object.entries(filters).some(
    ([k, v]) => k !== 'sort' && (Array.isArray(v) ? v.length : v),
  )

  async function run(offset = 0) {
    if (browse && !hasFilters) return
    setState({ status: 'loading' })
    try {
      const data = await search({ q: q.trim(), mode, k: K, offset, ...filters })
      setState({ status: 'done', data })
    } catch (err) {
      setState({ status: 'error', message: err.message })
    }
  }

  function onSubmit(e) {
    e.preventDefault()
    run(0)
  }

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda semántica, por palabra clave y por filtros</div>
          <form onSubmit={onSubmit}>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza (o deja vacío y filtra)"
              autoFocus
            />
            <select value={mode} onChange={(e) => setMode(e.target.value)} title="Modo de búsqueda" disabled={browse}>
              {MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : browse ? 'Filtrar' : 'Buscar'}
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap layout">
          <FilterPanel filters={filters} onChange={setFilters} browse={browse} />

          <section className="results">
            {state.status === 'error' && <div className="err">Error: {state.message}</div>}

            {state.status === 'done' && (
              <>
                <div className="meta">{state.data.count} resultado(s) · modo {state.data.mode}</div>
                {state.data.errors && (
                  <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>
                )}
                {state.data.results.length > 0 ? (
                  <>
                    {state.data.results.map((r) => <ResultCard key={r._id || r.syndication_id} r={r} />)}
                    {state.data.count === K && (
                      <button className="more" onClick={() => run((state.data.offset || 0) + K)}>
                        Cargar más
                      </button>
                    )}
                  </>
                ) : (
                  <div className="empty">Sin resultados.</div>
                )}
              </>
            )}

            {state.status === 'idle' && (
              <div className="empty">Escribe una consulta o aplica filtros y pulsa Buscar.</div>
            )}
          </section>
        </div>
      </main>
    </>
  )
}
