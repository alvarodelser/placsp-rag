import { useEffect, useRef, useState } from 'react'
import { search, sendFeedback, removeFeedback } from './api.js'
import { EMPTY, EXPLORE, filtersToParams, activeFilterList } from './filters.js'
import FilterRail from './components/FilterRail.jsx'
import FilterDrawer from './components/FilterDrawer.jsx'
import ActiveFilters from './components/ActiveFilters.jsx'
import CpvSelect from './components/CpvSelect.jsx'
import NutsSelect from './components/NutsSelect.jsx'
import MultiCheck from './components/MultiCheck.jsx'
import BudgetRange from './components/BudgetRange.jsx'
import DateTimeline from './components/DateTimeline.jsx'
import ResultCard from './components/ResultCard.jsx'
import statusMap from './codelists/status.json'
import resultMap from './codelists/result.json'
import typeMap from './codelists/contract_type.json'
import procMap from './codelists/procedure.json'

const MODES = [['hybrid', 'Híbrida'], ['vector', 'Semántica'], ['keyword', 'Palabra clave']]
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

const TABS = [
  { id: 'cpv', label: 'CPV', fields: ['cpv'] },
  { id: 'nuts', label: 'Ubicación', fields: ['nuts'] },
  { id: 'status', label: 'Estado', fields: ['status'] },
  { id: 'result', label: 'Resultado', fields: ['result'] },
  { id: 'contract_type', label: 'Tipo', fields: ['contract_type'] },
  { id: 'procedure', label: 'Procedimiento', fields: ['procedure'] },
  { id: 'dates', label: 'Fechas', fields: ['dates', 'open_only'] },
  { id: 'budget', label: 'Presupuesto', fields: ['budget'] },
]

export default function App() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [filters, setFilters] = useState(EXPLORE)
  const [openTab, setOpenTab] = useState(null)
  const [state, setState] = useState({ status: 'idle' })
  const [sessionId] = useState(getSessionId)
  const [searchId, setSearchId] = useState(null)
  const [searchedFilters, setSearchedFilters] = useState(EXPLORE)
  const [liked, setLiked] = useState(() => new Set())
  const didMount = useRef(false)

  const browse = q.trim() === ''
  const hasFilters = activeFilterList(filters).length > 0

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
        const results = state.data.results.map((res, i) => ({
          id: resultId(res),
          rank: (state.data.offset || 0) + i,
          score: res._score ?? null,
        }))
        await sendFeedback({
          search_id: searchId, session_id: sessionId,
          query: state.data.query || '', mode: state.data.mode,
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

  function patch(p) { setFilters((f) => ({ ...f, ...p })) }
  function setList(field, vals) { patch({ [field]: vals }) }

  function removeFilter(field, value) {
    if (['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure'].includes(field)) {
      patch({ [field]: filters[field].filter((v) => v !== value) })
    } else if (field === 'dates') patch({ pub_from: '', pub_to: '' })
    else if (field === 'open_only') patch({ open_only: false })
    else if (field === 'budget') patch({ budget_min: '', budget_max: '' })
  }

  const counts = {}
  for (const e of activeFilterList(filters)) {
    const tab = TABS.find((t) => t.fields.includes(e.field))
    if (tab) counts[tab.id] = (counts[tab.id] || 0) + 1
  }

  function drawerContent(id) {
    switch (id) {
      case 'cpv': return <CpvSelect value={filters.cpv} onChange={(v) => setList('cpv', v)} />
      case 'nuts': return <NutsSelect value={filters.nuts} onChange={(v) => setList('nuts', v)} />
      case 'status': return <MultiCheck map={statusMap} value={filters.status} onChange={(v) => setList('status', v)} />
      case 'result': return <MultiCheck map={resultMap} value={filters.result} onChange={(v) => setList('result', v)} />
      case 'contract_type': return <MultiCheck map={typeMap} value={filters.contract_type} onChange={(v) => setList('contract_type', v)} />
      case 'procedure': return <MultiCheck map={procMap} value={filters.procedure} onChange={(v) => setList('procedure', v)} />
      case 'dates': return <DateTimeline filters={filters} onChange={patch} />
      case 'budget': return <BudgetRange filters={filters} onChange={patch} />
      default: return null
    }
  }

  const openTabDef = TABS.find((t) => t.id === openTab)

  return (
    <>
      <header>
        <div className="wrap">
          <h1>Búsqueda de licitaciones · PLACSP</h1>
          <div className="sub">Contratación del sector público — búsqueda y filtros</div>
          <form onSubmit={(e) => { e.preventDefault(); run(0) }}>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="p. ej. servicios de limpieza (o deja vacío y filtra)" autoFocus />
            <select value={mode} onChange={(e) => setMode(e.target.value)} title="Modo de búsqueda" disabled={browse}>
              {MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
            <button type="submit" disabled={state.status === 'loading'}>
              {state.status === 'loading' ? 'Buscando…' : browse ? 'Filtrar' : 'Buscar'}
            </button>
            <button type="button" className="explore-btn" onClick={() => { setFilters(EXPLORE); setQ(''); run(0, EXPLORE, '') }}>
              Explorar
            </button>
          </form>
        </div>
      </header>

      <main>
        <div className="wrap layout">
          <section className="results">
            <ActiveFilters filters={filters} onRemove={removeFilter} onClear={() => { setFilters(EMPTY); setState({ status: 'idle' }) }} />

            {state.status === 'error' && <div className="err">Error: {state.message}</div>}

            {state.status === 'done' && (
              <>
                <div className="meta">{state.data.count} resultado(s) · modo {state.data.mode}</div>
                {state.data.errors && <div className="err">Weaviate: {JSON.stringify(state.data.errors)}</div>}
                {state.data.results.length > 0 ? (
                  <>
                    {state.data.results.map((r) => (
                      <ResultCard
                        key={resultId(r)}
                        r={r}
                        liked={liked.has(resultId(r))}
                        onToggleLike={() => toggleLike(r)}
                      />
                    ))}
                    {state.data.count === K && (
                      <button className="more" onClick={() => run((state.data.offset || 0) + K)}>Cargar más</button>
                    )}
                  </>
                ) : <div className="empty">Sin resultados.</div>}
              </>
            )}

            {state.status === 'idle' && (
              <div className="empty">Escribe una consulta o aplica un filtro.</div>
            )}
          </section>

          <FilterRail tabs={TABS} counts={counts} openTab={openTab} onOpen={setOpenTab} />
          {openTabDef && (
            <FilterDrawer title={openTabDef.label} onClose={() => setOpenTab(null)}>
              {drawerContent(openTab)}
            </FilterDrawer>
          )}
        </div>
      </main>
    </>
  )
}
