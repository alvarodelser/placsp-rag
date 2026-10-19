// search-ui/src/pilot/DocHover.jsx — a document at a glance, on hover: its role, date and summary,
// and the passages where the pipeline found what matters most in it (criteria, requirements,
// guarantees first) with the found name marked. Wrap any trigger with it; clicking is the caller's.
import { useRef, useState } from 'react'
import { docPreview } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { CircleNotch } from '../icons.js'

const cache = new Map()      // sha|tender -> promise: a preview is fetched once per page load
const W = 420

export default function DocHover({ tenderId, sha, children, className = '' }) {
  const [card, setCard] = useState(null)
  const timer = useRef(null)
  const el = useRef(null)

  function enter() {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      // Below the trigger (above it near the bottom of the window), never over the row itself.
      const r = el.current.getBoundingClientRect()
      const below = window.innerHeight - r.bottom > 360
      const pos = { left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)),
                    ...(below ? { top: r.bottom + 6 } : { bottom: window.innerHeight - r.top + 6 }) }
      setCard({ pos, status: 'loading' })
      const key = `${sha}|${tenderId}`
      if (!cache.has(key)) cache.set(key, docPreview(sha, tenderId).catch((e) => { cache.delete(key); throw e }))
      cache.get(key).then((d) => setCard((c) => c && { ...c, status: 'done', d }))
        .catch((e) => setCard((c) => c && { ...c, status: 'error', e: e.message }))
    }, 250)
  }
  function leave() { clearTimeout(timer.current); setCard(null) }

  return (
    <span ref={el} className={`dh ${className}`} onMouseEnter={enter} onMouseLeave={leave}>
      {children}
      {card && (
        <div className="dh-card" style={{ ...card.pos, width: W }} role="tooltip">
          {card.status === 'loading' && <div className="loading-state"><CircleNotch size={18} className="spinner" /></div>}
          {card.status === 'error' && <div className="err">{card.e}</div>}
          {card.status === 'done' && <Preview d={card.d} />}
        </div>
      )}
    </span>
  )
}

function Preview({ d }) {
  const doc = d.document
  return (
    <>
      <div className="doc-meta">
        <span className="chip">{roleEs(doc.role)}</span>
        {doc.seq != null && <span className="muted">Doc {doc.seq}</span>}
        <time>{doc.effective_date || 'sin fecha'}</time>
        {doc.pages ? <span className="muted">{doc.pages} pág.</span> : null}
      </div>
      <div className="dh-title">{doc.filename || doc.title}</div>
      {doc.summary && <p className="dh-sum">{doc.summary}</p>}
      {d.spans.length > 0 && (
        <div className="dh-spans">
          <div className="np-rel">Qué se encontró <span>{d.mentions} menciones</span></div>
          {d.spans.map((s) => (
            <div key={s.entity_id} className="dh-span">
              <span className="dh-kind" style={{ color: nodeInfo(s.label).color }}>{nodeInfo(s.label).es}{s.page ? ` · pág. ${s.page}` : ''}</span>
              <p>…{s.before}<mark style={{ borderColor: nodeInfo(s.label).color }}>{s.mark}</mark>{s.after}…</p>
            </div>
          ))}
        </div>
      )}
      <div className="dh-foot">Clic para leerlo con sus anotaciones</div>
    </>
  )
}
