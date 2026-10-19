// search-ui/src/pilot/DocView.jsx — a document as the pipeline read it: its text, chunk by chunk,
// with every mention highlighted where it was found. Named mentions are filled, references that do
// not name the entity ("la empresa", "la adjudicataria") are underlined. Clicking one opens its entity.
import { useEffect, useMemo, useRef, useState } from 'react'
import { getDocument, fileUrl } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { CircleNotch } from '../icons.js'
import NodePanel from './NodePanel.jsx'
import { go } from './route.js'

const PAGE = /\[Página (\d+)\]/g
const BATCH = 40

export default function DocView({ tenderId, sha, focusChunk, focusEntity }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(focusEntity || null)
  const [hidden, setHidden] = useState(new Set())
  const [loading, setLoading] = useState(false)
  const scrolled = useRef(false)

  async function load(start) {
    setLoading(true)
    try {
      const d = await getDocument(sha, tenderId, start, BATCH)
      setData((cur) => (cur && start > 0 ? { ...d, chunks: [...cur.chunks, ...d.chunks], entities: { ...cur.entities, ...d.entities } } : d))
    } catch (e) {
      setError(e.message)
    }
    setLoading(false)
  }
  // Start where the reader is going (the chunk of a mention), with a little before it.
  useEffect(() => { scrolled.current = false; setData(null); load(Math.max(0, (Number(focusChunk) || 0) - 2)) }, [sha, tenderId]) // eslint-disable-line
  useEffect(() => {
    if (!data || scrolled.current) return
    const el = document.querySelector(focusEntity ? `.dv-chunk mark[data-e="${CSS.escape(focusEntity)}"]` : `#chunk-${focusChunk}`)
    if (el) { el.scrollIntoView({ block: 'center' }); scrolled.current = true }
  }, [data, focusChunk, focusEntity])

  const counts = useMemo(() => {
    const c = {}
    for (const ch of data?.chunks || []) for (const m of ch.mentions || []) {
      const key = m.entity_id
      c[key] = (c[key] || 0) + 1
    }
    return Object.entries(c).map(([id, n]) => ({ id, n, ...(data.entities[id] || { name: id, label: '?' }) }))
      .sort((a, b) => b.n - a.n)
  }, [data])
  const labels = useMemo(() => [...new Set(counts.map((c) => c.label))], [counts])

  if (error) return <div className="err">{error}</div>
  if (!data) return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  const d = data.document
  const first = data.chunks[0]?.chunk_idx || 0
  const next = data.start + data.chunks.length
  return (
    <div className="dv">
      <div className="tv-head dv-head">
        <button type="button" className="linkish" onClick={() => go(`/t/${tenderId}`)}>← {d.tender_name || tenderId}</button>
        <div className="doc-meta">
          <span className="chip">Doc {d.seq} · {roleEs(d.role)}</span>
          <time>{d.effective_date || 'sin fecha'}</time>
          <span className="muted">{data.total_chunks} fragmentos</span>
          {d.stored && <a href={fileUrl(sha)} target="_blank" rel="noreferrer">Archivo guardado</a>}
          {d.url && <a href={d.url} target="_blank" rel="noreferrer">Original ↗</a>}
        </div>
        <h2>{d.title || d.filename}</h2>
        {d.summary && <p className="tv-desc">{d.summary}</p>}
        <div className="pg-legend dv-legend">
          {labels.map((l) => (
            <button key={l} type="button" className={`pg-key ${hidden.has(l) ? 'off' : ''}`}
              onClick={() => setHidden((h) => { const n = new Set(h); n.has(l) ? n.delete(l) : n.add(l); return n })}>
              <i style={{ background: nodeInfo(l).color }} />{nodeInfo(l).es}
            </button>
          ))}
          <span className="pg-note">relleno = nombrada · subrayado = referencia («la empresa»…)</span>
        </div>
      </div>
      <div className="dv-body">
        <article className="dv-text">
          {first > 0 && <button type="button" className="more" onClick={() => { scrolled.current = true; setData(null); load(Math.max(0, first - BATCH)) }}>Fragmentos anteriores</button>}
          {data.chunks.map((c) => (
            <section key={c.chunk_idx} id={`chunk-${c.chunk_idx}`} className="dv-chunk">
              <div className="dv-chunk-head">Fragmento {c.chunk_idx + 1}{c.page_from ? ` · pág. ${c.page_from}${c.page_to && c.page_to !== c.page_from ? `–${c.page_to}` : ''}` : ''}
                {c.ner !== 'ok' && <span className="muted"> · sin extracción</span>}</div>
              <Annotated text={c.text} mentions={c.mentions || []} entities={data.entities} hidden={hidden}
                selected={selected} onPick={setSelected} sha={sha} storedFile={d.stored} />
            </section>
          ))}
          {next < data.total_chunks && <button type="button" className="more" disabled={loading} onClick={() => load(next)}>{loading ? 'Cargando…' : 'Más fragmentos'}</button>}
        </article>
        <aside className="dv-side">
          <div className="np-rel">Entidades en estos fragmentos</div>
          <ul className="np-list">
            {counts.filter((c) => !hidden.has(c.label)).map((c) => (
              <li key={c.id}><button type="button" className={`linkish ${selected === c.id ? 'on' : ''}`} onClick={() => setSelected(c.id)}>
                <i style={{ background: nodeInfo(c.label).color }} />{c.name}<span className="muted"> · {c.n}</span></button></li>
            ))}
          </ul>
        </aside>
      </div>
      {selected && <NodePanel id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </div>
  )
}

// The chunk text cut into plain runs, highlighted mentions and page breaks. A mention is drawn on
// the name itself when the pipeline found it inside the quote, else on the whole quote; overlapping
// mentions keep the first one.
function Annotated({ text, mentions, entities, hidden, selected, onPick, sha, storedFile }) {
  const spans = mentions
    .map((m) => ({ ...m, a: m.name_start ?? m.char_start, b: m.name_end ?? m.char_end, label: entities[m.entity_id]?.label }))
    .filter((m) => m.a != null && m.b != null && m.b > m.a && !hidden.has(m.label))
    .sort((x, y) => x.a - y.a || y.b - x.b)
  const kept = []
  for (const m of spans) if (!kept.length || m.a >= kept[kept.length - 1].b) kept.push(m)
  const out = []
  let at = 0
  const plain = (s, key) => {
    const parts = []
    let last = 0
    for (const p of s.matchAll(PAGE)) {
      parts.push(s.slice(last, p.index))
      parts.push(<span key={`${key}-p${p.index}`} className="dv-page">
        {storedFile ? <a href={fileUrl(sha, p[1])} target="_blank" rel="noreferrer">pág. {p[1]}</a> : `pág. ${p[1]}`}</span>)
      last = p.index + p[0].length
    }
    parts.push(s.slice(last))
    return parts
  }
  kept.forEach((m, i) => {
    if (m.a > at) out.push(...plain(text.slice(at, m.a), `t${i}`))
    const e = entities[m.entity_id] || {}
    const c = nodeInfo(m.label).color
    out.push(
      <mark key={`m${i}`} data-e={m.entity_id} className={`${m.kind === 'coref' ? 'ref' : ''} ${selected === m.entity_id ? 'on' : ''}`}
        style={m.kind === 'coref' ? { borderBottomColor: c } : { background: `${c}22`, borderBottomColor: c }}
        title={`${nodeInfo(m.label).es}: ${e.name || m.entity_id}${m.kind === 'coref' ? ' (referencia)' : ''}`}
        onClick={() => onPick(m.entity_id)}>{text.slice(m.a, m.b)}</mark>)
    at = m.b
  })
  out.push(...plain(text.slice(at), 'end'))
  return <p className="dv-p">{out}</p>
}
