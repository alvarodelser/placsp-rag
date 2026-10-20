// search-ui/src/pilot/PilotApp.jsx — viewer for the document pilot, separate from the search app.
// Reads only /api/pilot (the pilot_* Qdrant collections and the :Pilot graph).
// One search on top (contracts, companies, authorities or all) narrows the list on the left and
// lights its hits on the pilot's graph in the middle. A tender, a company or a document opens on
// its own page; going back returns to the list and graph as they were left.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { listTenders, search, health, corpusGraph } from './pilotApi.js'
import { CHANNEL, nodeInfo, roleEs, shortTitle } from './labels.js'
import { money } from '../format.js'
import { Landmark, Building2, LoaderCircle, FileText, Search, X } from '../icons.js'
import TenderView from './TenderView.jsx'
import CompanyView from './CompanyView.jsx'
import DocView from './DocView.jsx'
import ForceCanvas from './ForceCanvas.jsx'
import NodePanel from './NodePanel.jsx'
import { go, parse, useHash } from './route.js'
import './pilot.css'

// The filters a search can take, each in the colour its nodes have on the graph. No filter searches all.
const SCOPES = [['tenders', 'Contratos', FileText, 'Tender'], ['companies', 'Empresas', Building2, 'Company'],
  ['authorities', 'Órganos', Landmark, 'Authority']]

export default function PilotApp() {
  const route = parse(useHash())
  const [query, setQuery] = useState({ q: route.params.q || '', scope: 'all' })
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
        </div>
      </header>
      <main>
        {problems.map(([k, v]) => <div key={k} className="wrap err"><b>{k}</b>: {v}</div>)}
        <div className={`wrap playout ${home ? '' : 'full'}`}>
          {home && <ResultList res={res} current={current} onOrg={(id) => go(`/c/${encodeURIComponent(id)}`)} />}
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

// Filters sit quietly above the bar. Picking one flies it into the bar as the search button, in its
// colour; the row then offers "En todo" and the other filters.
function SearchBar({ query, onSearch }) {
  const [q, setQ] = useState(query.q)
  useEffect(() => setQ(query.q), [query.q])
  const scope = SCOPES.find(([k]) => k === query.scope)
  const btn = useRef(null)
  const from = useRef(null)

  useLayoutEffect(() => {
    const r = from.current
    from.current = null
    const el = btn.current
    if (!r || !el?.animate || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const to = el.getBoundingClientRect()
    el.animate([
      { transform: `translate(${r.left - to.left}px, ${r.top - to.top}px)`, width: `${r.width}px`, height: `${r.height}px`, borderRadius: '999px' },
      { transform: 'none', width: `${to.width}px`, height: `${to.height}px` },
    ], { duration: 340, easing: 'cubic-bezier(.2,.8,.2,1)' })
  }, [query.scope])

  const pick = (k, e) => { from.current = e.currentTarget.getBoundingClientRect(); onSearch({ q, scope: k }) }
  const [, label, Icon, node] = scope || []
  return (
    <div className="psearch-wrap">
      <div className="pfilters" role="group" aria-label="Buscar en">
        {scope && (
          <button type="button" className="pf-clear" onClick={() => onSearch({ q, scope: 'all' })}>
            <Search size={13} strokeWidth={2.5} /> En todo
          </button>
        )}
        {SCOPES.filter(([k]) => k !== query.scope).map(([k, l, I, n]) => (
          <button key={k} type="button" className="pf" style={{ '--k': nodeInfo(n).color }} onClick={(e) => pick(k, e)}>
            <I size={14} /> {l}
          </button>
        ))}
      </div>
      <form className="pbar psearch" onSubmit={(e) => { e.preventDefault(); onSearch({ ...query, q }) }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar"
          placeholder="Buscar por significado: «servicio de limpieza», «solvencia volumen de negocios», una empresa…" />
        {q && <button type="button" className="icon-btn" aria-label="Borrar" onClick={() => { setQ(''); onSearch({ ...query, q: '' }) }}><X size={15} /></button>}
        <button ref={btn} type="submit" className="pgo" style={scope ? { '--k': nodeInfo(node).color } : undefined}>
          {scope ? <><Icon size={16} /> {label}</> : <><Search size={16} strokeWidth={2.5} /> Buscar</>}
        </button>
      </form>
    </div>
  )
}

function ResultList({ res, current, onOrg }) {
  if (res.status === 'loading') return <aside className="plist"><div className="loading-state"><LoaderCircle size={22} className="spinner" /></div></aside>
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
              <span className="pitem-name" title={t.name}>{shortTitle(t)}</span>
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
  // A search lights its hits.
  const hits = res.status === 'done' && !res.d.latest
    ? [...res.d.tenders.map((t) => `tender:${t.tender_id}`), ...res.d.organizations.map((o) => o.id)] : null

  function open(n) {
    if (n.label === 'Tender') go(`/t/${n.id.replace(/^tender:/, '')}`)
    else if (['Organization', 'Company', 'Authority'].includes(n.label)) go(`/c/${encodeURIComponent(n.id)}`)
    else if (n.label === 'Document') go(`/t/${n.tender.replace(/^tender:/, '')}/d/${n.id.replace(/^doc:/, '')}`)
  }
  if (!graph) return <div className="loading-state"><LoaderCircle size={28} className="spinner" /></div>
  if (graph.error) return <div className="err">{graph.error}</div>
  return (
    <>
      <ForceCanvas graph={graph} selected={selected} onSelect={setSelected} onOpen={open} highlight={hits} height="calc(100vh - 170px)"
        toolbar={<span className="pg-note">clic: detalle · doble clic: abrir</span>} />
      {selected && <NodePanel id={selected} seen={graph.nodes.find((n) => n.id === selected)} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </>
  )
}
