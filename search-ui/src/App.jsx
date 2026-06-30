import { useEffect, useRef, useState } from 'react'
import { search, facets, sendFeedback, removeFeedback } from './api.js'
import { EMPTY, EXPLORE, filtersToParams, activeFilterList, removeValues } from './filters.js'
import FilterWorkspace from './components/FilterWorkspace.jsx'
import ActiveFilters from './components/ActiveFilters.jsx'
import ResultCard from './components/ResultCard.jsx'
import { SlidersHorizontal } from './icons.js'
import statusMap from './codelists/status.json'

const K = 15

// One stable anonymous id per browser, so a person's relevance judgments can be
// grouped without any login.
function getSessionId() {
  let id = localStorage.getItem('placsp_session_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('placsp_session_id', id)
  }
  return id
}

const resultId = (r) => r._id || r.syndication_id

export default function App() {
  const [q, setQ] = useState('')
  const [filters, setFilters] = useState(EXPLORE)
  const mode = 'hybrid'  // always use hybrid search
const [filtersOpen, setFiltersOpen] = useState(false)
  const [facetsData, setFacetsData] = useState({ nuts: {}, dates: { publication: [], plazo: [] } })
  const [total, setTotal] = useState(null)
  const [state, setState] = useState({ status: 'idle' })
  const [sessionId] = useState(getSessionId)
  const [searchId, setSearchId] = useState(null)
  const [searchedFilters, setSearchedFilters] = useState(EXPLORE)
  const [liked, setLiked] = useState(() => new Set())
  const didMount = useRef(false)



  async function run(offset = 0, f = filters, query = q) {
    if (query.trim() === '' && activeFilterList(f).length === 0) {
      setState({ status: 'idle' })
      return
    }
    // A new query (offset 0) starts a fresh feedback context; "Cargar más" keeps it.
    if (offset === 0) {
      setSearchId(crypto.randomUUID())
      setSearchedFilters(f)
      setLiked(new Set())
    }
    setState({ status: 'loading' })
    try {
      const data = await search({ q: query.trim(), mode, k: K, offset, ...filtersToParams(f) })
      setState({ status: 'done', data })
    } catch (err) {
      setState({ status: 'error', message: err.message })
    }
  }

  // Toggle a "relevant" judgment, optimistically; revert the UI if the call fails.
  async function toggleLike(r) {
    if (!searchId || state.status !== 'done') return
    const id = resultId(r)
    const wasLiked = liked.has(id)
    setLiked((prev) => {
      const next = new Set(prev)
      wasLiked ? next.delete(id) : next.add(id)
      return next
    })
    try {
      if (wasLiked) {
        await removeFeedback({ search_id: searchId, result_id: id })
      } else {
        const results = (state.data?.results || []).map((res, i) => ({
          id: resultId(res),
          rank: (state.data?.offset || 0) + i,
          score: res._score ?? null,
        }))
        await sendFeedback({
          search_id: searchId, session_id: sessionId,
          query: state.data?.query || '', mode: state.data?.mode,
          filters: searchedFilters, results, result_id: id,
        })
      }
    } catch {
      setLiked((prev) => {
        const next = new Set(prev)
        wasLiked ? next.add(id) : next.delete(id)
        return next
      })
    }
  }

  // Auto-run the EXPLORE default once on mount.
  useEffect(() => {
    if (didMount.current) return
    didMount.current = true
    run(0, EXPLORE, '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced facets fetch — drives live count + map shading.
  useEffect(() => {
    const params = filtersToParams(filters)
    const id = setTimeout(async () => {
      try {
        const f = await facets({ q: q.trim(), ...params })
        setFacetsData(f); setTotal(q.trim() ? null : f.total)
      } catch (err) {
        console.warn('facets fetch failed:', err.message)
        // degrade silently — filtering still works, histograms stay blank
      }
    }, 250)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, q])

  function patch(p) { setFilters((f) => ({ ...f, ...p })) }
  function setList(field, vals) { patch({ [field]: vals }) }

  function removeFilter(field, value) {
    if (['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure'].includes(field)) {
      patch({ [field]: removeValues(filters[field], value) })
    } else if (field === 'dates') patch({ pub_from: '', pub_to: '' })
    else if (field === 'deadline') patch({ deadline_from: '', deadline_to: '' })
    else if (field === 'open_only') patch({ open_only: false })
    else if (field === 'budget') patch({ budget_min: '', budget_max: '' })
  }

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda y filtros</div>
          <form onSubmit={(e) => { e.preventDefault(); run(0) }}>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza (o deja vacío y filtra)" autoFocus />
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : 'Buscar'}
            </button>
            <button type="button" className="filtros-btn" onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal size={18} /> Filtros
              {activeFilterList(filters).length > 0 && <span className="filtros-badge">{activeFilterList(filters).length}</span>}
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap layout">
          <section className="results">
            <ActiveFilters filters={filters} onRemove={removeFilter} />

            {state.status === 'error' && <div className="err">Error: {state.message}</div>}

            {state.status === 'done' && (
              <>
                <div className="meta">
                  {total != null ? `${total.toLocaleString('es-ES')} contratos` : `${(state.data?.results || []).length} resultado(s)`}
                  {state.data?.mode && state.data.mode !== 'browse' ? ` · ${state.data.mode}` : ''}
                </div>
                {state.data?.errors && <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>}
                {(state.data?.results || []).length > 0 ? (
                  <>
                    {(state.data?.results || []).map((r) => (
                      <ResultCard
                        key={resultId(r)}
                        r={r}
                        liked={liked.has(resultId(r))}
                        onToggleLike={() => toggleLike(r)}
                      />
                    ))}
                    {((state.data?.total != null
                      ? (state.data?.offset || 0) + (state.data?.results || []).length < state.data?.total
                      : state.data?.count === K)) && (
                      <button className="more" onClick={() => run((state.data?.offset || 0) + K)}>Cargar más</button>
                    )}
                  </>
                ) : <div className="empty">Sin resultados.</div>}
              </>
            )}

            {state.status === 'idle' && (
              <div className="empty">Escribe una consulta o aplica un filtro.</div>
            )}
          </section>

          {filtersOpen && (
            <FilterWorkspace
              filters={filters} patch={patch} setList={setList}
              facetsData={facetsData} total={total}
              previewResults={state.status === 'done' ? (state.data?.results || []) : []}
              loading={state.status === 'loading'}
              onClose={() => { setFiltersOpen(false); run(0) }}
              onClear={() => { setFilters(EMPTY); setState({ status: 'idle' }) }}
            />
          )}
        </div>
      </main>
    </>
  )
}
