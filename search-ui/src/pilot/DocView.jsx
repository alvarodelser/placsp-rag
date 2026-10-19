// search-ui/src/pilot/DocView.jsx — a document as the pipeline read it, beside the original.
//  - The text, chunk by chunk, with every mention marked where it was found: named mentions are
//    filled, references that do not name the entity ("la empresa") underlined. Lines the PDF breaks
//    mid-sentence are joined and the lines every page repeats (headers, footers, signatures) folded,
//    without moving a character, so the pipeline's offsets still land on their words.
//  - The original (pdf.js, or the notice as published) follows the text page by page; a mention
//    clicked is marked in the original too.
//  - An entity in focus (from a link, or clicked) gets a navigator over all its mentions here.
import { useEffect, useMemo, useRef, useState } from 'react'
import { getDocument, fileUrl } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { CircleNotch } from '../icons.js'
import NodePanel from './NodePanel.jsx'
import OriginalPane from './OriginalPane.jsx'
import { reflow, lineKeyRanges } from './doctext.js'
import { go } from './route.js'

const PAGE = /\[Página (\d+)\]/g
const BATCH = 40
const MODES = [['text', 'Texto'], ['split', 'Texto y original'], ['original', 'Original']]

export default function DocView({ tenderId, sha, focusChunk, focusEntity }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [entity, setEntity] = useState(focusEntity || null)
  const [panel, setPanel] = useState(null)
  const [hidden, setHidden] = useState(new Set())
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState(() => { try { return localStorage.getItem('pilot.docmode') || 'split' } catch { return 'split' } })
  const [target, setTarget] = useState(null)        // {page, quote} for the original
  const [nth, setNth] = useState(0)
  const pending = useRef(null)                      // a mention to scroll to once its chunk is loaded
  const arrived = useRef(false)                     // the link's own entity was taken to its mention
  const synced = useRef({ page: null, until: 0 })   // the original follows the text, unless just aimed

  async function load(start, keep = false) {
    setLoading(true)
    try {
      const d = await getDocument(sha, tenderId, start, BATCH, entity || '')
      setData((cur) => (cur && keep ? { ...d, chunks: [...cur.chunks, ...d.chunks], entities: { ...cur.entities, ...d.entities } } : d))
    } catch (e) {
      setError(e.message)
    }
    setLoading(false)
  }
  // Start where the reader is going (the chunk of a mention), with a little before it.
  useEffect(() => {
    setData(null)
    arrived.current = false
    pending.current = focusChunk != null ? { chunk_idx: Number(focusChunk), first: true } : null
    load(Math.max(0, (Number(focusChunk) || 0) - 2))
  }, [sha, tenderId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem('pilot.docmode', mode) } catch { /* private window */ } }, [mode])

  // A new entity in focus: fetch where it is mentioned in the whole document, keep the text loaded.
  useEffect(() => {
    if (!data || !entity) return
    getDocument(sha, tenderId, data.start, 1, entity).then((d) => setData((cur) => cur && ({ ...cur, focus: d.focus, entities: { ...d.entities, ...cur.entities } })))
    setNth(0)
  }, [entity]) // eslint-disable-line react-hooks/exhaustive-deps

  // A link to an entity lands on its mention nearest to the linked chunk (a chunk may name it only
  // through a reference the pipeline placed elsewhere).
  useEffect(() => {
    if (!data || arrived.current || !entity || !(data.focus || []).length) return
    arrived.current = true
    const c = Number(focusChunk) || 0
    const k = Math.max(0, data.focus.findIndex((f) => f.chunk_idx >= c))
    goTo(k)
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  // The original follows the page at the top of the text.
  useEffect(() => {
    let t = null
    const on = () => {
      clearTimeout(t)
      t = setTimeout(() => {
        if (Date.now() < synced.current.until) return
        const secs = [...document.querySelectorAll('.dv-chunk')]
        const top = secs.find((el) => el.getBoundingClientRect().bottom > 180)
        const page = Number(top?.dataset.page) || null
        if (page && page !== synced.current.page) { synced.current.page = page; setTarget({ page, follow: true }) }
      }, 150)
    }
    window.addEventListener('scroll', on, { passive: true })
    return () => { window.removeEventListener('scroll', on); clearTimeout(t) }
  }, [])

  // Scroll to what is pending (a link's mention, or the navigator's) once it is in the page.
  useEffect(() => {
    if (!data || !pending.current) return
    const p = pending.current
    const sel = p.at != null ? `mark[data-k="${p.chunk_idx}:${p.at}"]` : entity && p.first
      ? `#chunk-${p.chunk_idx} mark[data-e="${CSS.escape(entity)}"]` : `#chunk-${p.chunk_idx}`
    const el = document.querySelector(sel) || document.querySelector(`#chunk-${p.chunk_idx}`)
    if (!el) return
    el.scrollIntoView({ block: 'center' })
    pending.current = null
    if (el.tagName === 'MARK') el.click()
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  const counts = useMemo(() => {
    const c = {}
    for (const ch of data?.chunks || []) for (const m of ch.mentions || []) c[m.entity_id] = (c[m.entity_id] || 0) + 1
    return Object.entries(c).map(([id, n]) => ({ id, n, ...(data.entities[id] || { name: id, label: '?' }) }))
      .sort((a, b) => b.n - a.n)
  }, [data])
  const labels = useMemo(() => [...new Set(counts.map((c) => c.label))], [counts])
  const boiler = useMemo(() => new Set(data?.boilerplate || []), [data])

  if (error) return <div className="err">{error}</div>
  if (!data) return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  const d = data.document
  const first = data.chunks[0]?.chunk_idx || 0
  const next = data.start + data.chunks.length
  const focus = entity ? data.focus || [] : []
  const canOriginal = d.stored

  function goTo(k) {
    const f = focus[k]
    if (!f) return
    setNth(k)
    const loaded = data.chunks.some((c) => c.chunk_idx === f.chunk_idx)
    pending.current = f
    if (loaded) setData({ ...data })        // re-run the scroll effect
    else load(Math.max(0, f.chunk_idx - 2))
  }
  function pick(m, chunk) {
    setEntity(m.entity_id)
    const quote = chunk.text.slice(m.a, m.b)
    synced.current.until = Date.now() + 1500
    setTarget({ page: m.page || chunk.page_from, quote: quote.length >= 6 ? quote : chunk.text.slice(m.char_start ?? m.a, m.char_end ?? m.b) })
    const k = focus.findIndex((f) => f.chunk_idx === chunk.chunk_idx && f.at === m.a)
    if (k >= 0) setNth(k)
  }

  const text = (
    <article className="dv-text">
      {first > 0 && <button type="button" className="more" onClick={() => load(Math.max(0, first - BATCH))}>Fragmentos anteriores</button>}
      {data.chunks.map((c) => (
        <section key={c.chunk_idx} id={`chunk-${c.chunk_idx}`} data-page={c.page_from || ''} className={`dv-chunk ${c.ner !== 'ok' ? 'no-ner' : ''}`}>
          <div className="dv-chunk-head" title={c.ner !== 'ok' ? 'Este fragmento no pasó por la extracción de entidades' : ''}>
            {c.chunk_idx + 1}{c.ner !== 'ok' && <span> · sin extracción</span>}</div>
          <Annotated chunk={c} entities={data.entities} hidden={hidden} entity={entity} boiler={boiler}
            onPick={(m) => pick(m, c)} onPage={(p) => { synced.current.until = Date.now() + 1500; setTarget({ page: p }) }} />
        </section>
      ))}
      {next < data.total_chunks && <button type="button" className="more" disabled={loading} onClick={() => load(next, true)}>{loading ? 'Cargando…' : 'Más fragmentos'}</button>}
    </article>
  )

  return (
    <div className="dv">
      <div className="tv-head dv-head">
        <button type="button" className="linkish" onClick={() => go(`/t/${tenderId}`)}>← {d.tender_name || tenderId}</button>
        <div className="doc-meta">
          <span className="chip">Doc {d.seq} · {roleEs(d.role)}</span>
          <time>{d.effective_date || 'sin fecha'}</time>
          {d.pages ? <span className="muted">{d.pages} págs.</span> : null}
          <span className="muted">{data.total_chunks} fragmentos</span>
          {d.stored && <a href={fileUrl(sha)} target="_blank" rel="noreferrer">Archivo guardado</a>}
          {d.url && <a href={d.url} target="_blank" rel="noreferrer">En PLACSP ↗</a>}
        </div>
        <h2>{d.filename || d.title}</h2>
        {d.summary && <p className="tv-desc">{d.summary}</p>}
      </div>

      <div className="dv-bar">
        {canOriginal && (
          <span className="pg-modes">{MODES.map(([k, l]) => <button key={k} type="button" className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{l}</button>)}</span>
        )}
        {entity && (
          <span className="dv-nav">
            <i style={{ background: nodeInfo(data.entities[entity]?.label).color }} />
            <b>{data.entities[entity]?.name || entity}</b>
            {focus.length > 0 && <>
              <button type="button" className="icon-btn" aria-label="Anterior" disabled={nth <= 0} onClick={() => goTo(nth - 1)}>‹</button>
              <span>{nth + 1} de {focus.length}</span>
              <button type="button" className="icon-btn" aria-label="Siguiente" disabled={nth >= focus.length - 1} onClick={() => goTo(nth + 1)}>›</button>
            </>}
            <button type="button" className="linkish small" onClick={() => setPanel(entity)}>Ficha</button>
            <button type="button" className="icon-btn" aria-label="Quitar" onClick={() => { setEntity(null); setTarget(null) }}>×</button>
          </span>
        )}
        <details className="dv-ents">
          <summary>Entidades en el texto cargado ({counts.length})</summary>
          <div className="pg-legend dv-legend">
            {labels.map((l) => (
              <button key={l} type="button" className={`pg-key ${hidden.has(l) ? 'off' : ''}`}
                onClick={() => setHidden((h) => { const n = new Set(h); n.has(l) ? n.delete(l) : n.add(l); return n })}>
                <i style={{ background: nodeInfo(l).color }} />{nodeInfo(l).es}
              </button>
            ))}
            <span className="pg-note">relleno = nombrada · subrayado = referencia («la empresa»…)</span>
          </div>
          <ul className="np-list dv-entlist">
            {counts.filter((c) => !hidden.has(c.label)).map((c) => (
              <li key={c.id}><button type="button" className={`linkish ${entity === c.id ? 'on' : ''}`} onClick={() => setEntity(c.id)}>
                <i style={{ background: nodeInfo(c.label).color }} />{c.name}<span className="muted"> · {c.n}</span></button></li>
            ))}
          </ul>
        </details>
      </div>

      <div className={`dv-body mode-${canOriginal ? mode : 'text'}`}>
        {(mode !== 'original' || !canOriginal) && text}
        {canOriginal && mode !== 'text' && (
          <aside className="dv-orig"><OriginalPane sha={sha} ext={d.ext} target={target} /></aside>
        )}
      </div>
      {panel && <NodePanel id={panel} onSelect={setPanel} onClose={() => setPanel(null)} />}
    </div>
  )
}

// The chunk cut at every boundary that matters (a mention, a repeated line, a page marker), each
// piece drawn with what covers it. A mention is drawn on the name when the pipeline found it
// inside the quote, else on the whole quote; overlapping mentions keep the first one.
function Annotated({ chunk, entities, hidden, entity, boiler, onPick, onPage }) {
  const text = useMemo(() => reflow(chunk.text, boiler), [chunk.text, boiler])
  const spans = (chunk.mentions || [])
    .map((m) => ({ ...m, a: m.name_start ?? m.char_start, b: m.name_end ?? m.char_end, label: entities[m.entity_id]?.label }))
    .filter((m) => m.a != null && m.b != null && m.b > m.a && !hidden.has(m.label))
    .sort((x, y) => x.a - y.a || y.b - x.b)
  const kept = []
  for (const m of spans) if (!kept.length || m.a >= kept[kept.length - 1].b) kept.push(m)
  const boilers = lineKeyRanges(chunk.text, boiler)
  const pages = [...chunk.text.matchAll(PAGE)].map((p) => ({ a: p.index, b: p.index + p[0].length, page: Number(p[1]) }))

  const cuts = new Set([0, text.length])
  for (const r of [...kept, ...boilers, ...pages]) { cuts.add(r.a); cuts.add(r.b) }
  const points = [...cuts].filter((x) => x >= 0 && x <= text.length).sort((x, y) => x - y)
  const out = []
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1]
    const pg = pages.find((p) => p.a === a)
    if (pg) {
      out.push(<button key={`p${a}`} type="button" className="dv-page" onClick={() => onPage(pg.page)} title="Ver esta página en el original">Página {pg.page}</button>)
      i = points.indexOf(pg.b) - 1
      continue
    }
    const piece = text.slice(a, b)
    const m = kept.find((x) => x.a <= a && b <= x.b)
    const dim = boilers.some((x) => x.a <= a && b <= x.b)
    if (!m) { out.push(dim ? <span key={a} className="dv-boiler">{piece}</span> : piece); continue }
    const c = nodeInfo(m.label).color
    const e = entities[m.entity_id] || {}
    out.push(
      <mark key={a} data-e={m.entity_id} data-k={m.a === a ? `${chunk.chunk_idx}:${m.a}` : undefined}
        className={`${m.kind === 'coref' ? 'ref' : ''} ${entity === m.entity_id ? 'on' : ''} ${dim ? 'dv-boiler' : ''}`}
        style={m.kind === 'coref' ? { borderBottomColor: c } : { background: `${c}${entity === m.entity_id ? '44' : '1f'}`, borderBottomColor: c }}
        title={`${nodeInfo(m.label).es}: ${e.name || m.entity_id}${m.kind === 'coref' ? ' (referencia)' : ''}${m.page ? ` · pág. ${m.page}` : ''}`}
        onClick={() => onPick(m)}>{piece}</mark>)
  }
  return <p className="dv-p">{out}</p>
}
