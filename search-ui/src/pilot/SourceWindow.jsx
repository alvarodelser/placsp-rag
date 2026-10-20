// search-ui/src/pilot/SourceWindow.jsx — where a cited passage comes from, in a window over the
// answer: the original where it was published, at the passage's page, or the passage as the
// pipeline read it with the quoted sentence marked.
// Links out go to the whole document in the app and to where it was published.
import { useEffect, useState } from 'react'
import { getDocument } from './pilotApi.js'
import { roleEs } from './labels.js'
import OriginalPane from './OriginalPane.jsx'
import { X, ArrowRight } from '../icons.js'
import { ExtLink, Loading, SourceRef, Tabs } from './ui.jsx'
import { go } from './route.js'

const PAGE = /\[Página (\d+)\]/g

// The page the quote is on: the last page marker before it in the passage, else where it starts.
function pageOf(text, at, from) {
  let page = from
  for (const m of text.matchAll(PAGE)) if (m.index <= at) page = Number(m[1])
  return page || 1
}

export default function SourceWindow({ passage: p, quote, onClose }) {
  const [doc, setDoc] = useState(null)
  const [view, setView] = useState('original')
  useEffect(() => {
    let live = true
    getDocument(p.doc_sha256, p.tender_id, p.chunk_idx, 1)
      .then((d) => { if (!live) return; setDoc(d.document); if (!d.document?.url) setView('text') })
      .catch((e) => live && setDoc({ error: e.message }))
    return () => { live = false }
  }, [p.doc_sha256, p.tender_id, p.chunk_idx])
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const text = p.text.replace(/[ \t]+/g, ' ')
  const q = (quote || '').replace(/^…|…$/g, '').trim()
  const at = q ? text.indexOf(q) : -1
  const page = pageOf(text, Math.max(0, at), p.page_from)

  return (
    <div className="sw" role="dialog" aria-label="Fuente de la respuesta" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="sw-box">
        <div className="sw-head">
          <div className="sw-title">
            <SourceRef role={p.doc_role} seq={p.doc_seq} page={page} />
            <b title={p.doc_title}>{doc?.filename || p.doc_title || roleEs(p.doc_role)}</b>
            <button type="button" className="icon-btn" aria-label="Cerrar" onClick={onClose}><X size={16} /></button>
          </div>
          <Tabs items={[['original', 'Original'], ['text', 'Fragmento']]} value={view} onChange={setView} extra={<>
            <button type="button" className="linkish" onClick={() => go(`/t/${p.tender_id}/d/${p.doc_sha256}?c=${p.chunk_idx}`)}>Abrir en el documento <ArrowRight size={13} className="ico" /></button>
            <ExtLink href={doc?.url}>Abrir donde se publicó</ExtLink>
          </>} />
        </div>
        {view === 'text' ? (
          <div className="sw-text">
            <p>{at < 0 ? text : <>{text.slice(0, at)}<mark>{text.slice(at, at + q.length)}</mark>{text.slice(at + q.length)}</>}
              {p.text.length >= 900 ? '…' : ''}</p>
          </div>
        ) : !doc ? <div className="op-empty"><Loading /></div>
          : doc.error ? <div className="op-empty">{doc.error}</div>
          : <OriginalPane url={doc.url} ext={doc.ext} page={page} title={doc.filename || p.doc_title} archive={!!doc.in_archive} />}
      </div>
    </div>
  )
}
