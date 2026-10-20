// search-ui/src/pilot/SourceHover.jsx — where an extracted thing comes from, on hover: the passages
// of the documents that mention it, the found words marked. A click opens the first one in the
// document viewer, scrolled to it and highlighted.
import { useRef, useState } from 'react'
import { getNode } from './pilotApi.js'
import { roleEs } from './labels.js'
import { LoaderCircle } from '../icons.js'
import { go } from './route.js'

const cache = new Map()
const W = 440
const load = (id) => {
  if (!cache.has(id)) cache.set(id, getNode(id).catch((e) => { cache.delete(id); throw e }))
  return cache.get(id)
}

export default function SourceHover({ id, children }) {
  const [card, setCard] = useState(null)
  const timer = useRef(null)
  const el = useRef(null)

  function enter() {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const r = el.current.getBoundingClientRect()
      const below = window.innerHeight - r.bottom > 320
      setCard({ pos: { left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)),
                       ...(below ? { top: r.bottom + 6 } : { bottom: window.innerHeight - r.top + 6 }) }, status: 'loading' })
      load(id).then((d) => setCard((c) => c && { ...c, status: 'done', d }))
        .catch((e) => setCard((c) => c && { ...c, status: 'error', e: e.message }))
    }, 250)
  }
  function leave() { clearTimeout(timer.current); setCard(null) }
  async function open() {
    const d = await load(id).catch(() => null)
    const m = d?.mentions.find((x) => x.doc_sha256)
    if (m) go(`/t/${m.tender_id}/d/${m.doc_sha256}?c=${m.chunk_idx}&e=${encodeURIComponent(id)}`)
  }

  return (
    <span ref={el} className="dh sh" onMouseEnter={enter} onMouseLeave={leave} onClick={open} role="link" tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') open() }}>
      {children}
      {card && (
        <div className="dh-card" style={{ ...card.pos, width: W }} role="tooltip">
          {card.status === 'loading' && <div className="loading-state"><LoaderCircle size={18} className="spinner" /></div>}
          {card.status === 'error' && <div className="err">{card.e}</div>}
          {card.status === 'done' && <Sources d={card.d} />}
        </div>
      )}
    </span>
  )
}

function Sources({ d }) {
  const ms = d.mentions.slice(0, 3)
  if (!ms.length) {
    return <div className="small muted">{d.node.source === 'feed' ? 'Del anuncio en el feed de PLACSP: no se encontró en los documentos.' : 'Sin menciones localizadas.'}</div>
  }
  return (
    <>
      <div className="np-rel">Dónde se encontró <span>{d.mention_count} menciones</span></div>
      {ms.map((m, i) => (
        <div key={i} className="ref-box">
          <span className="ref-tag">{roleEs(m.doc_role)}{m.doc_seq != null ? ` · doc ${m.doc_seq}` : ''}{m.page ? ` · pág. ${m.page}` : ''}</span>
          <p>{m.before && '…'}{flat(m.before).slice(-110)}<mark>{flat(m.quote)}</mark>{flat(m.after).slice(0, 130)}…</p>
        </div>
      ))}
      <div className="dh-foot">Clic para abrir el documento en esta mención</div>
    </>
  )
}

const flat = (s) => (s || '').replace(/\s+/g, ' ')
