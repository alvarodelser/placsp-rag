// search-ui/src/pilot/DocView.jsx — a document as the pipeline read it.
//  - The text, chunk by chunk, plain: lines a PDF broke mid-sentence joined, the lines every page
//    repeats (headers, footers, signatures) folded, without moving a character so the pipeline's
//    offsets still land on their words.
//  - Provenance on demand: with an entity in focus (from a link, or picked from the list), each of
//    its references in this document is framed, tagged with the document and page on its top left,
//    the found name in bold; a navigator steps through all of them.
//  - The original (pdf.js, or the notice as published) opens in a window over the text, at the
//    reference clicked, framed and tagged the same way.
import { useEffect, useMemo, useRef, useState } from 'react'
import { getDocument } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { LoaderCircle, X, ArrowLeft, ArrowUpRight } from '../icons.js'
import NodePanel from './NodePanel.jsx'
import OriginalPane from './OriginalPane.jsx'
import { reflow, lineKeyRanges, blocks } from './doctext.js'
import { go } from './route.js'

const PAGE = /\[Página (\d+)\]/g
const BATCH = 40

export default function DocView({ tenderId, sha, focusChunk, focusEntity }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [entity, setEntity] = useState(focusEntity || null)
  const [panel, setPanel] = useState(null)
  const [loading, setLoading] = useState(false)
  const [original, setOriginal] = useState(null)     // the window: null, or {page, quote, tag}
  const [nth, setNth] = useState(0)
  const pending = useRef(null)                       // a reference to scroll to once its chunk is loaded
  const arrived = useRef(false)                      // the link's own entity was taken to its reference

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
    pending.current = focusChunk != null ? { chunk_idx: Number(focusChunk) } : null
    load(Math.max(0, (Number(focusChunk) || 0) - 2))
  }, [sha, tenderId]) // eslint-disable-line react-hooks/exhaustive-deps

  // A new entity in focus: where it is referenced in the whole document.
  useEffect(() => {
    if (!data || !entity) return
    getDocument(sha, tenderId, data.start, 1, entity).then((d) => setData((cur) => cur && ({ ...cur, focus: d.focus, entities: { ...d.entities, ...cur.entities } })))
    setNth(0)
  }, [entity]) // eslint-disable-line react-hooks/exhaustive-deps

  // A link to an entity lands on its reference nearest to the linked chunk.
  useEffect(() => {
    if (!data || arrived.current || !entity || !(data.focus || []).length) return
    arrived.current = true
    const c = Number(focusChunk) || 0
    goTo(Math.max(0, data.focus.findIndex((f) => f.chunk_idx >= c)))
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to what is pending once it is in the page; a chunk opened from an answer flashes.
  useEffect(() => {
    if (!data || !pending.current) return
    const p = pending.current
    const el = (p.at != null && document.querySelector(`[data-k="${p.chunk_idx}:${p.at}"]`)) || document.querySelector(`#chunk-${p.chunk_idx}`)
    if (!el) return
    el.scrollIntoView({ block: 'center' })
    pending.current = null
    if (el.tagName === 'SECTION') { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash') }
  }, [data])

  const counts = useMemo(() => {
    const c = {}
    for (const ch of data?.chunks || []) for (const m of ch.mentions || []) c[m.entity_id] = (c[m.entity_id] || 0) + 1
    return Object.entries(c).map(([id, n]) => ({ id, n, ...(data.entities[id] || { name: id, label: '?' }) }))
      .sort((a, b) => b.n - a.n)
  }, [data])
  const boiler = useMemo(() => new Set(data?.boilerplate || []), [data])

  if (error) return <div className="err">{error}</div>
  if (!data) return <div className="loading-state"><LoaderCircle size={28} className="spinner" /></div>
  const d = data.document
  const first = data.chunks[0]?.chunk_idx || 0
  const next = data.start + data.chunks.length
  const focus = entity ? data.focus || [] : []
  const tagOf = (page) => `${roleEs(d.role)}${d.seq != null ? ` · doc ${d.seq}` : ''}${page ? ` · pág. ${page}` : ''}`

  function goTo(k) {
    const f = (data.focus || [])[k]
    if (!f) return
    setNth(k)
    pending.current = f
    if (data.chunks.some((c) => c.chunk_idx === f.chunk_idx)) setData({ ...data })
    else load(Math.max(0, f.chunk_idx - 2))
  }
  function openAt(ref, chunk) {
    const page = ref.page || chunk.page_from
    setOriginal({ page, quote: chunk.text.slice(ref.a, ref.b), tag: tagOf(page) })
  }

  return (
    <div className="dv">
      <div className="tv-head dv-head">
        <button type="button" className="linkish" onClick={() => go(`/t/${tenderId}`)}><ArrowLeft size={13} className="ico" /> {d.tender_name || tenderId}</button>
        <div className="doc-meta">
          <span className="chip">Doc {d.seq} · {roleEs(d.role)}</span>
          <time>{d.effective_date || 'sin fecha'}</time>
          {d.pages ? <span className="muted">{d.pages} págs.</span> : null}
          {d.stored && <button type="button" className="linkish" onClick={() => setOriginal({ page: data.chunks[0]?.page_from || 1 })}>Ver el original</button>}
          {d.url && <a href={d.url} target="_blank" rel="noreferrer">En PLACSP <ArrowUpRight size={13} className="ico" /></a>}
        </div>
        <h2>{d.filename || d.title}</h2>
        {d.summary && <p className="tv-desc">{d.summary}</p>}
      </div>

      <div className="dv-bar">
        {entity ? (
          <span className="dv-nav">
            <i style={{ background: nodeInfo(data.entities[entity]?.label).color }} />
            <b>{data.entities[entity]?.name || entity}</b>
            {focus.length > 0 ? <>
              <button type="button" className="icon-btn" aria-label="Anterior" disabled={nth <= 0} onClick={() => goTo(nth - 1)}>‹</button>
              <span>{nth + 1} de {focus.length}</span>
              <button type="button" className="icon-btn" aria-label="Siguiente" disabled={nth >= focus.length - 1} onClick={() => goTo(nth + 1)}>›</button>
            </> : <span className="muted">sin referencias en este documento</span>}
            <button type="button" className="linkish small" onClick={() => setPanel(entity)}>Ficha</button>
            <button type="button" className="icon-btn" aria-label="Quitar" onClick={() => setEntity(null)}>×</button>
          </span>
        ) : <span className="muted small">Elige una entidad para ver dónde la cita este documento.</span>}
        <details className="dv-ents">
          <summary>Entidades en el texto cargado ({counts.length})</summary>
          <ul className="np-list dv-entlist">
            {counts.map((c) => (
              <li key={c.id}><button type="button" className={`linkish ${entity === c.id ? 'on' : ''}`} onClick={() => setEntity(c.id)}>
                <i style={{ background: nodeInfo(c.label).color }} />{c.name}<span className="muted"> · {c.n}</span></button></li>
            ))}
          </ul>
        </details>
      </div>

      <article className="dv-text">
        {first > 0 && <button type="button" className="more" onClick={() => load(Math.max(0, first - BATCH))}>Fragmentos anteriores</button>}
        {data.chunks.map((c) => (
          <section key={c.chunk_idx} id={`chunk-${c.chunk_idx}`} className={`dv-chunk ${c.ner !== 'ok' ? 'no-ner' : ''}`}>
            <div className="dv-chunk-head" title={c.ner !== 'ok' ? 'Este fragmento no pasó por la extracción de entidades' : ''}>
              {c.chunk_idx + 1}{c.ner !== 'ok' && <span> · sin extracción</span>}</div>
            <Annotated chunk={c} entity={entity} boiler={boiler} tagOf={tagOf}
              onOpen={d.stored ? (ref) => openAt(ref, c) : null} onPage={d.stored ? (p) => setOriginal({ page: p }) : null} />
          </section>
        ))}
        {next < data.total_chunks && <button type="button" className="more" disabled={loading} onClick={() => load(next, true)}>{loading ? 'Cargando…' : 'Más fragmentos'}</button>}
      </article>

      {original && d.stored && (
        <div className="dv-window" role="dialog" aria-label="Documento original" onClick={(e) => { if (e.target === e.currentTarget) setOriginal(null) }}>
          <div className="dv-window-box">
            <div className="dv-window-head">
              <b>{d.filename || d.title}</b>
              {original.tag && <span className="ref-tag static">{original.tag}</span>}
              <button type="button" className="icon-btn" aria-label="Cerrar" onClick={() => setOriginal(null)}><X size={16} /></button>
            </div>
            <OriginalPane sha={sha} ext={d.ext} target={original} />
          </div>
        </div>
      )}
      {panel && <NodePanel id={panel} onSelect={setPanel} onClose={() => setPanel(null)} />}
    </div>
  )
}

// The chunk laid out as blocks (headings, a notice's label/value rows, list items, paragraphs, page
// dividers), repeated lines folded; the focused entity's references framed (their quote, the name
// in bold) and tagged with document and page. A reference across two blocks is framed in each.
function Annotated({ chunk, entity, boiler, tagOf, onOpen, onPage }) {
  const text = useMemo(() => reflow(chunk.text, boiler), [chunk.text, boiler])
  const layout = useMemo(() => blocks(text), [text])
  const refs = []
  for (const m of (chunk.mentions || []).filter((x) => x.entity_id === entity)
    .map((x) => ({ ...x, a: x.char_start ?? x.name_start, b: x.char_end ?? x.name_end, key: x.name_start ?? x.char_start ?? 0 }))
    .filter((x) => x.a != null && x.b > x.a).sort((x, y) => x.a - y.a)) {
    if (!refs.length || m.a >= refs[refs.length - 1].b) refs.push(m)
  }
  const boilers = lineKeyRanges(chunk.text, boiler)
  const pages = [...chunk.text.matchAll(PAGE)].map((p) => ({ a: p.index, b: p.index + p[0].length, page: Number(p[1]) }))

  // Plain text between references: page markers become dividers, repeated lines are folded.
  function plain(from, to, key) {
    const cuts = new Set([from, to])
    for (const r of [...boilers, ...pages]) for (const x of [r.a, r.b]) if (x > from && x < to) cuts.add(x)
    const pts = [...cuts].sort((x, y) => x - y)
    const out = []
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1]
      const pg = pages.find((p) => p.a === a)
      if (pg) {
        out.push(onPage
          ? <button key={`${key}p${a}`} type="button" className="dv-page" onClick={() => onPage(pg.page)} title="Ver esta página en el original">Página {pg.page}</button>
          : <span key={`${key}p${a}`} className="dv-page">Página {pg.page}</span>)
        continue
      }
      if (pages.some((p) => a >= p.a && b <= p.b)) continue
      const piece = text.slice(a, b)
      out.push(boilers.some((x) => x.a <= a && b <= x.b) ? <span key={`${key}${a}`} className="dv-boiler">{piece}</span> : piece)
    }
    return out
  }

  // [from, to) of the text with the references inside it framed.
  function span(from, to, key) {
    const out = []
    let at = from
    refs.forEach((r, i) => {
      const a = Math.max(r.a, from), b = Math.min(r.b, to)
      if (b <= a) return
      if (a > at) out.push(...plain(at, a, `${key}t${i}`))
      const ns = Math.max(a, r.name_start ?? r.a), ne = Math.min(b, r.name_end ?? r.b)
      out.push(
        <mark key={`${key}r${i}`} className={`ref-frame ${r.kind === 'coref' ? 'is-ref' : ''} ${onOpen ? 'can-open' : ''}`} data-k={`${chunk.chunk_idx}:${r.key}`}
          data-tag={tagOf(r.page || chunk.page_from)}
          title={`${r.kind === 'coref' ? 'Referencia sin nombre («la empresa»…)' : 'Referencia'}${onOpen ? ' · clic: verla en el original' : ''}`}
          onClick={() => onOpen?.(r)}>
          {ne > ns ? <>{text.slice(a, ns)}<b>{text.slice(ns, ne)}</b>{text.slice(ne, b)}</> : text.slice(a, b)}
        </mark>)
      at = b
    })
    if (to > at) out.push(...plain(at, to, `${key}end`))
    return out
  }

  const out = []
  for (let i = 0; i < layout.length; i++) {
    const x = layout[i], key = `b${x.a}`
    if (x.type === 'page') {
      out.push(<div key={key} className="dv-pagebreak">{onPage
        ? <button type="button" className="dv-page" onClick={() => onPage(x.page)} title="Ver esta página en el original">Página {x.page}</button>
        : <span className="dv-page">Página {x.page}</span>}</div>)
    } else if (x.type === 'field') {
      const rows = []
      for (; i < layout.length && layout[i].type === 'field'; i++) {
        const f = layout[i]
        rows.push(<div key={`f${f.a}`} className="dv-field"><dt>{span(f.la, f.lb, `l${f.a}`)}</dt><dd>{span(f.va, f.vb, `v${f.a}`)}</dd></div>)
      }
      i--
      out.push(<dl key={key} className="dv-fields">{rows}</dl>)
    } else if (x.type === 'heading') {
      out.push(<h4 key={key} className={`dv-h ${x.sub ? 'sub' : ''}`}>{span(x.a, x.b, key)}</h4>)
    } else if (x.type === 'item') {
      out.push(<p key={key} className="dv-p dv-li">{span(x.a, x.b, key)}</p>)
    } else {
      out.push(<p key={key} className="dv-p">{span(x.a, x.b, key)}</p>)
    }
  }
  return <div className="dv-flow">{out}</div>
}
