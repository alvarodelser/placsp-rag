// search-ui/src/pilot/PilotApp.jsx — viewer for the document pilot, separate from the search app.
// Reads only /api/pilot (the pilot_* Qdrant collections and the :Pilot graph).
import { useEffect, useState } from 'react'
import { overview, listTenders, health } from './pilotApi.js'
import { CHANNEL } from './labels.js'
import { money } from '../format.js'
import { CircleNotch } from '../icons.js'
import TenderView from './TenderView.jsx'
import CompanyView from './CompanyView.jsx'
import AskView from './AskView.jsx'
import DocView from './DocView.jsx'
import ExploreView from './ExploreView.jsx'
import { go, parse, useHash } from './route.js'
import './pilot.css'

export default function PilotApp() {
  const route = parse(useHash())
  return (
    <div className="pilot">
      <header>
        <div className="wrap header-top">
          <div className="brand">
            <h1>Piloto documental · PLACSP</h1>
            <div className="sub">Todos los documentos de cada expediente, unificados en un objeto, un grafo y fragmentos</div>
          </div>
          <nav className="pnav">
            <button type="button" className={route.kind === 'home' || route.kind === 't' ? 'on' : ''} onClick={() => go('')}>Expedientes</button>
            <button type="button" className={route.kind === 'explore' ? 'on' : ''} onClick={() => go('/explore')}>Explorar</button>
            <button type="button" className={route.kind === 'ask' ? 'on' : ''} onClick={() => go('/ask')}>Preguntar</button>
            <a href="#/">← Búsqueda</a>
          </nav>
        </div>
      </header>
      <main>
        <div className={`wrap playout ${['ask', 'explore'].includes(route.kind) || route.doc ? 'full' : ''}`}>
          {!['ask', 'explore'].includes(route.kind) && !route.doc && <TenderList current={route.kind === 't' ? route.id : null} />}
          <section className="pmain">
            {route.kind === 'home' && <Overview />}
            {route.kind === 't' && !route.doc && <TenderView key={route.id} id={route.id} />}
            {route.kind === 't' && route.doc && <DocView key={`${route.id}/${route.doc}`} tenderId={route.id} sha={route.doc}
              focusChunk={route.params.c} focusEntity={route.params.e} />}
            {route.kind === 'explore' && <ExploreView />}
            {route.kind === 'c' && <CompanyView key={route.id} id={route.id} />}
            {route.kind === 'ask' && <AskView key={route.params.q || ''} initial={route.params.q || ''} />}
          </section>
        </div>
      </main>
    </div>
  )
}

function TenderList({ current }) {
  const [q, setQ] = useState('')
  const [channel, setChannel] = useState('')
  const [state, setState] = useState({ status: 'loading' })

  async function run(query = q, ch = channel) {
    setState({ status: 'loading' })
    try {
      setState({ status: 'done', d: await listTenders({ q: query.trim(), channel: ch, limit: 100 }) })
    } catch (e) {
      setState({ status: 'error', e: e.message })
    }
  }
  useEffect(() => { run() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside className="plist">
      <form onSubmit={(e) => { e.preventDefault(); run() }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por significado…" />
      </form>
      <div className="chips">
        {['', ...Object.keys(CHANNEL)].map((c) => (
          <button key={c || 'all'} type="button" className={`chip linkchip ${channel === c ? 'on' : ''}`}
            onClick={() => { setChannel(c); run(q, c) }}>{c ? CHANNEL[c] : 'Todos'}</button>
        ))}
      </div>
      {state.status === 'loading' && <div className="loading-state"><CircleNotch size={22} className="spinner" /></div>}
      {state.status === 'error' && <div className="err">{state.e}</div>}
      {state.status === 'done' && (
        <ul>
          {state.d.results.map((t) => (
            <li key={t.tender_id}>
              <button type="button" className={`pitem ${current === t.tender_id ? 'on' : ''}`} onClick={() => go(`/t/${t.tender_id}`)}>
                <span className="pitem-top"><span className="badge">{CHANNEL[t.channel] || t.channel}</span>
                  <span className="muted">{t.published}</span>{t.score != null && <span className="score">{t.score}</span>}</span>
                <span className="pitem-name">{t.name}</span>
                <span className="muted small">{t.authority?.name}</span>
                <span className="muted small">{t.counts?.documents ?? 0} docs · {t.counts?.lots ?? 0} lotes{t.value != null ? ` · ${money(t.value)}` : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

function Overview() {
  const [state, setState] = useState({ status: 'loading' })
  const [h, setH] = useState(null)
  useEffect(() => {
    overview().then((d) => setState({ status: 'done', d })).catch((e) => setState({ status: 'error', e: e.message }))
    health().then(setH).catch(() => {})
  }, [])
  const problems = h ? ['qdrant', 'neo4j', 'vectorizer'].filter((k) => String(h[k]).startsWith('error')) : []
  if (state.status === 'loading') return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  if (state.status === 'error') return <div className="err">{state.e}</div>
  const d = state.d
  return (
    <div className="tv">
      {problems.map((k) => <div key={k} className="err"><b>{k}</b>: {String(h[k]).replace(/^error: /, '')}</div>)}
      <div className="tv-head">
        <h2>Qué contiene el piloto</h2>
        <div className="tv-counts">
          <span><b>{d.counts.tenders}</b> expedientes</span>
          <span><b>{d.counts.documents}</b> documentos</span>
          <span><b>{d.counts.chunks.toLocaleString('es-ES')}</b> fragmentos</span>
          <span><b>{d.counts.entities.toLocaleString('es-ES')}</b> entidades</span>
          <span><b>{d.analysable}</b> analizables</span>
        </div>
        <div className="chips">{Object.entries(d.channels).map(([c, n]) => <span key={c} className="chip">{CHANNEL[c] || c} · {n}</span>)}</div>
      </div>
      <div className="tv-grid">
        <section className="tv-card">
          <h3>Empresas en más expedientes</h3>
          <ul className="plain">{d.top_companies.map((c) => <li key={c.id}><button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(c.id)}`)}>{c.name}<span className="muted"> · {c.tenders}</span></button></li>)}</ul>
        </section>
        <section className="tv-card">
          <h3>Órganos con más expedientes</h3>
          <ul className="plain">{d.top_authorities.map((c) => <li key={c.id}><button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(c.id)}`)}>{c.name}<span className="muted"> · {c.tenders}</span></button></li>)}</ul>
        </section>
        <section className="tv-card wide">
          <h3>Cómo usarlo</h3>
          <ul className="plain">
            <li><b>Expediente:</b> el objeto unificado (lotes, criterios, solvencia, resultado), sus documentos en orden y su grafo.</li>
            <li><b>Grafo:</b> qué viene del feed y qué se extrajo de cada documento; pulsa un nodo para ver su evidencia y los fragmentos que lo mencionan.</li>
            <li><b>Empresa:</b> en qué expedientes aparece, con qué papel, contra quién compite y para qué órganos trabaja.</li>
            <li><b>Preguntar:</b> los fragmentos y entidades más cercanos a una pregunta, con su contexto en el grafo.</li>
          </ul>
        </section>
      </div>
    </div>
  )
}
