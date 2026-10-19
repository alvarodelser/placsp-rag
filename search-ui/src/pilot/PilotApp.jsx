// search-ui/src/pilot/PilotApp.jsx — viewer for the document pilot, separate from the search app.
// Reads only /api/pilot (the pilot_* Qdrant collections and the :Pilot graph).
// One search on top (contracts, companies, authorities or all) narrows the list on the left and
// lights its hits on the pilot's graph in the middle; a tender, a company or a document opens in
// the middle instead, with the list kept.
import { useEffect, useState } from 'react'
import { listTenders, search, health, corpusGraph } from './pilotApi.js'
import { CHANNEL, roleEs } from './labels.js'
import { money } from '../format.js'
import { CircleNotch, X } from '../icons.js'
import TenderView from './TenderView.jsx'
import CompanyView from './CompanyView.jsx'
import DocView from './DocView.jsx'
import ForceCanvas from './ForceCanvas.jsx'
import NodePanel from './NodePanel.jsx'
import { go, parse, useHash } from './route.js'
import './pilot.css'

const SCOPES = [['tenders', 'Contratos'], ['companies', 'Empresas'], ['authorities', 'Órganos'], ['all', 'Todo']]

export default function PilotApp() {
  const route = parse(useHash())
  const [query, setQuery] = useState({ q: route.params.q || '', scope: 'tenders' })
  const [res, setRes] = useState({ status: 'loading' })
  const [problems, setProblems] = useState([])

  useEffect(() => {
    health().then((h) => setProblems(['qdrant', 'neo4j', 'vectorizer'].filter((k) => String(h[k]).startsWith('error'))
      .map((k) => [k, String(h[k]).replace(/^error: /, '')]))).catch(() => {})
  }, [])
  useEffect(() => {
    let live = true
    setRes({ status: 'loading' })
    const q = query.q.trim()
    const p = q ? search({ q, scope: query.scope })
      : listTenders({ limit: 200 }).then((d) => ({ tenders: d.results, organizations: [], latest: true }))
    p.then((d) => live && setRes({ status: 'done', d })).catch((e) => live && setRes({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [query])

  const home = !['t', 'c'].includes(route.kind)
  const current = route.kind === 't' ? route.id : route.kind === 'c' ? route.id : null
  return (
    <div className="pilot">
      <header>
        <div className="wrap header-top">
          <div className="brand">
            <h1>Piloto documental · PLACSP</h1>
          </div>
          <SearchBar query={query} onSearch={(q) => { setQuery(q); if (!home) go('') }} />
          <a className="pback" href="#/">← Búsqueda</a>
        </div>
      </header>
      <main>
        {problems.map(([k, v]) => <div key={k} className="wrap err"><b>{k}</b>: {v}</div>)}
        <div className={`wrap playout ${route.doc ? 'full' : ''}`}>
          {!route.doc && <ResultList res={res} current={current} onOrg={(id) => go(`/c/${encodeURIComponent(id)}`)} />}
          <section className="pmain">
            {home && <Landing res={res} />}
            {route.kind === 't' && !route.doc && <TenderView key={route.id} id={route.id} />}
            {route.kind === 't' && route.doc && <DocView key={`${route.id}/${route.doc}`} tenderId={route.id} sha={route.doc}
              focusChunk={route.params.c} focusEntity={route.params.e} />}
            {route.kind === 'c' && <CompanyView key={route.id} id={route.id} />}
          </section>
        </div>
      </main>
    </div>
  )
}

function SearchBar({ query, onSearch }) {
  const [q, setQ] = useState(query.q)
  useEffect(() => setQ(query.q), [query.q])
  return (
    <form className="psearch" onSubmit={(e) => { e.preventDefault(); onSearch({ ...query, q }) }}>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar"
        placeholder="Buscar por significado: «servicio de limpieza», «solvencia volumen de negocios», una empresa…" />
      {q && <button type="button" className="icon-btn" aria-label="Borrar" onClick={() => { setQ(''); onSearch({ ...query, q: '' }) }}><X size={15} /></button>}
      <span className="pg-modes" role="group" aria-label="Buscar en">
        {SCOPES.map(([k, label]) => (
          <button key={k} type="button" className={query.scope === k ? 'on' : ''} onClick={() => onSearch({ q, scope: k })}>{label}</button>
        ))}
      </span>
    </form>
  )
}

function ResultList({ res, current, onOrg }) {
  if (res.status === 'loading') return <aside className="plist"><div className="loading-state"><CircleNotch size={22} className="spinner" /></div></aside>
  if (res.status === 'error') return <aside className="plist"><div className="err">{res.e}</div></aside>
  const { tenders, organizations, latest } = res.d
  return (
    <aside className="plist">
      <div className="plist-head muted small">
        {latest ? `${tenders.length} expedientes, los últimos primero`
          : `${tenders.length ? `${tenders.length} expedientes` : ''}${tenders.length && organizations.length ? ' · ' : ''}${organizations.length ? `${organizations.length} organizaciones` : ''}` || 'Sin resultados'}
      </div>
      <ul>
        {!latest && tenders.length > 0 && organizations.length > 0 && <li className="plist-sec">Expedientes</li>}
        {tenders.map((t) => (
          <li key={t.tender_id}>
            <button type="button" className={`pitem ${current === t.tender_id ? 'on' : ''}`} onClick={() => go(`/t/${t.tender_id}`)}>
              <span className="pitem-top"><span className="badge">{CHANNEL[t.channel] || t.channel}</span>
                <span className="muted">{t.published}</span></span>
              <span className="pitem-name">{t.name}</span>
              <span className="muted small">{t.authority?.name}</span>
              <span className="muted small">{t.counts?.documents ?? 0} docs · {t.counts?.lots ?? 0} lotes{t.value != null ? ` · ${money(t.value)}` : ''}</span>
              {(t.passages || []).slice(0, 1).map((p, i) => (
                <span key={i} className="pitem-hit"><b>{roleEs(p.doc_role)}{p.page_from ? ` · pág. ${p.page_from}` : ''}</b> {p.text.slice(0, 220)}…</span>
              ))}
            </button>
          </li>
        ))}
        {tenders.length > 0 && organizations.length > 0 && <li className="plist-sec">Organizaciones</li>}
        {organizations.map((o) => (
          <li key={o.id}>
            <button type="button" className={`pitem ${current === o.id ? 'on' : ''}`} onClick={() => onOrg(o.id)}>
              <span className="pitem-top">
                {o.kinds.map((k) => <span key={k} className={`badge ${k === 'authority' ? 'org-auth' : 'org-co'}`}>{k === 'authority' ? 'Órgano' : 'Empresa'}</span>)}
                <span className="muted">{o.tender_ids.length} exp.</span>
              </span>
              <span className="pitem-name">{o.name}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}

// The pilot as one graph: tenders, their authorities and their companies; documents on request.
function Landing({ res }) {
  const [graph, setGraph] = useState(null)
  const [selected, setSelected] = useState(null)
  useEffect(() => { corpusGraph({ documents: true }).then(setGraph).catch((e) => setGraph({ error: e.message })) }, [])
  const hits = res.status === 'done' && !res.d.latest
    ? [...res.d.tenders.map((t) => `tender:${t.tender_id}`), ...res.d.organizations.map((o) => o.id)] : null

  function open(n) {
    if (n.label === 'Tender') go(`/t/${n.id.replace(/^tender:/, '')}`)
    else if (['Organization', 'Company', 'Authority'].includes(n.label)) go(`/c/${encodeURIComponent(n.id)}`)
  }
  if (!graph) return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  if (graph.error) return <div className="err">{graph.error}</div>
  return (
    <>
      <ForceCanvas graph={graph} selected={selected} onSelect={setSelected} onOpen={open} highlight={hits}
        initiallyHidden={['Document']} height="calc(100vh - 150px)"
        toolbar={<span className="pg-note">clic: detalle · doble clic: abrir</span>} />
      {selected && <NodePanel id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </>
  )
}
