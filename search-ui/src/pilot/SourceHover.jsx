// search-ui/src/pilot/SourceHover.jsx — where an extracted thing comes from, on hover: one passage
// at a time of the documents that mention it (‹ › or the arrow keys swap them), the document it is
// in named on top, the found words highlighted. A click (on the thing, or "Ver en el original")
// opens the passage shown in the provenance window (SourceWindow), over the page.
import { useRef, useState } from 'react'
import SourceWindow from './SourceWindow.jsx'
import { getNode } from './pilotApi.js'
import { ChevronLeft, ChevronRight, Maximize2 } from '../icons.js'
import { ErrorNote, Loading, SourceRef } from './ui.jsx'

const cache = new Map()
const W = 460
const MENTIONS = 20
const load = (id) => {
  if (!cache.has(id)) cache.set(id, getNode(id, MENTIONS).catch((e) => { cache.delete(id); throw e }))
  return cache.get(id)
}

export default function SourceHover({ id, children, block = false }) {
  const [card, setCard] = useState(null)
  const [nth, setNth] = useState(0)
  const [win, setWin] = useState(null)               // the mention open in the window
  const timer = useRef(null)
  const el = useRef(null)

  // The card opens after a short pause and stays while the pointer is on it, so its arrows can be used.
  function enter() {
    clearTimeout(timer.current)
    if (card || win) return
    timer.current = setTimeout(() => {
      const r = el.current.getBoundingClientRect()
      const below = window.innerHeight - r.bottom > 340
      setNth(0)
      setCard({ pos: { left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)),
                       ...(below ? { top: r.bottom + 4 } : { bottom: window.innerHeight - r.top + 4 }) }, status: 'loading' })
      load(id).then((d) => setCard((c) => c && { ...c, status: 'done', d }))
        .catch((e) => setCard((c) => c && { ...c, status: 'error', e: e.message }))
    }, 250)
  }
  function leave() { clearTimeout(timer.current); timer.current = setTimeout(() => setCard(null), 220) }
  const ms = (card?.d?.mentions || []).filter((m) => m.doc_sha256)
  const step = (k) => setNth((n) => (n + k + ms.length) % ms.length)
  async function open(k = nth) {
    if (win) return
    const d = await load(id).catch(() => null)
    const list = (d?.mentions || []).filter((x) => x.doc_sha256)
    const m = list[k] || list[0]
    if (!m) return
    clearTimeout(timer.current)
    setCard(null)
    setWin(m)
  }
  function key(e) {
    if (win) return
    if (e.key === 'Enter') open()
    else if (card && ms.length > 1 && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) { e.preventDefault(); step(e.key === 'ArrowRight' ? 1 : -1) }
    else if (e.key === 'Escape') setCard(null)
  }

  return (
    <span ref={el} className={`dh sh ${block ? 'sh-block' : ''} ${card ? 'on' : ''}`} onMouseEnter={enter} onMouseLeave={leave}
      onFocus={enter} onBlur={leave} onClick={() => open()} role="link" tabIndex={0} onKeyDown={key}>
      {children}
      {card && (
        <div className="dh-card sh-card" style={{ ...card.pos, width: W }} role="dialog" aria-label="Dónde se encontró"
          onClick={(e) => e.stopPropagation()} onMouseEnter={() => clearTimeout(timer.current)}>
          {card.status === 'loading' && <Loading size={18} />}
          {card.status === 'error' && <ErrorNote>{card.e}</ErrorNote>}
          {card.status === 'done' && <Source d={card.d} ms={ms} nth={Math.min(nth, Math.max(0, ms.length - 1))} step={step} open={open} />}
        </div>
      )}
      {win && (
        <span onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <SourceWindow passage={asPassage(win)} quote={flat(win.quote)} onClose={() => setWin(null)} />
        </span>
      )}
    </span>
  )
}

// A mention as the window takes a passage: its quote with the words around it, where it is.
const asPassage = (m) => ({ tender_id: m.tender_id, doc_sha256: m.doc_sha256, chunk_idx: m.chunk_idx, doc_role: m.doc_role,
  doc_seq: m.doc_seq, doc_title: m.doc_title, page_from: m.page, text: flat(`${m.before || ''}${m.quote || ''}${m.after || ''}`) })

function Source({ d, ms, nth, step, open }) {
  if (!ms.length) {
    return <div className="small muted">{d.node.source === 'feed' ? 'Dato del anuncio publicado en la Plataforma: no se encontró en los documentos.' : 'Sin menciones localizadas.'}</div>
  }
  const m = ms[nth]
  const more = d.mention_count > ms.length ? ` · ${d.mention_count} en total` : ''
  return (
    <>
      <div className="sh-head">
        <span className="sh-title">Dónde se encontró</span>
        {ms.length > 1 && (
          <span className="sh-nav">
            <button type="button" className="icon-btn" aria-label="Anterior" onClick={() => step(-1)}><ChevronLeft size={15} /></button>
            <span>{nth + 1} de {ms.length}{more}</span>
            <button type="button" className="icon-btn" aria-label="Siguiente" onClick={() => step(1)}><ChevronRight size={15} /></button>
          </span>
        )}
      </div>
      <div className="sh-doc">
        <SourceRef role={m.doc_role} seq={m.doc_seq} page={m.page} />
        <span className="sh-doc-name" title={m.doc_title || ''}>{m.doc_title || 'Documento'}</span>
      </div>
      <blockquote className="sh-quote">
        {m.before ? '…' : ''}{lead(m.before)}<Quote m={m} />{tail(m.after)}{m.after ? '…' : ''}
      </blockquote>
      <div className="sh-foot">
        {m.kind === 'coref' && <span className="muted small">Referencia sin nombre («la empresa»…)</span>}
        <button type="button" className="linkish small" onClick={() => open(nth)}><Maximize2 size={12} className="ico" /> Ver en el original</button>
      </div>
    </>
  )
}

// The quote highlighted, the name inside it (when it is a longer passage) in bold.
function Quote({ m }) {
  const q = flat(m.quote), s = flat(m.surface)
  const i = s && s.length < q.length ? q.toLowerCase().indexOf(s.toLowerCase()) : -1
  return <mark className="sh-mark">{i < 0 ? q : <>{q.slice(0, i)}<b>{q.slice(i, i + s.length)}</b>{q.slice(i + s.length)}</>}</mark>
}

const flat = (s) => (s || '').replace(/\s+/g, ' ')
// Context cut at a word, so the passage never starts or ends mid-word.
const lead = (s) => { const x = flat(s).slice(-140); return x.length < flat(s).length ? x.replace(/^\S*\s/, '') : x }
const tail = (s) => { const x = flat(s).slice(0, 180); return x.length < flat(s).length ? x.replace(/\s\S*$/, '') : x }
