// search-ui/src/pilot/AskView.jsx — a question over one tender's documents, answered with citations.
// The passages come first (meaning + keywords, reordered by a reranker); the answer streams in as
// a small model writes it from them, each claim citing [n]. A citation points to its passage; a
// passage opens in the document viewer at its fragment.
import { useEffect, useRef, useState } from 'react'
import { answer } from './pilotApi.js'
import { roleEs } from './labels.js'
import { CircleNotch } from '../icons.js'
import { go } from './route.js'

const EXAMPLES = ['¿Qué solvencia económica se exige?', '¿Cuál es la garantía definitiva?', '¿Cómo se valora el precio?',
  '¿Qué penalidades hay por incumplimiento?', '¿Se permite subcontratar?', '¿Qué equipo mínimo se exige?']

export default function AskView({ tenderId }) {
  const [q, setQ] = useState('')
  const [st, setSt] = useState({ status: 'idle' })
  const [lit, setLit] = useState(null)
  const abort = useRef(null)
  useEffect(() => () => abort.current?.abort(), [])

  async function run(query = q) {
    if (!query.trim()) return
    abort.current?.abort()
    const ctl = new AbortController()
    abort.current = ctl
    setLit(null)
    setSt({ status: 'loading', q: query.trim(), text: '', passages: null })
    try {
      await answer({ q: query.trim(), tender_id: tenderId }, (e) => setSt((s) => {
        if (e.type === 'passages') return { ...s, passages: e.passages, info: e.info, model: e.model, status: 'writing' }
        if (e.type === 'token') return { ...s, text: s.text + e.text }
        if (e.type === 'done') return { ...s, status: 'done', text: e.text || s.text, cited: e.cited, ms: e.ms, note: e.note }
        if (e.type === 'error') return { ...s, status: 'error', error: e.error }
        return s
      }), ctl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setSt((s) => ({ ...s, status: 'error', error: e.message }))
    }
  }

  const busy = st.status === 'loading' || st.status === 'writing'
  return (
    <div className="ask">
      <form onSubmit={(e) => { e.preventDefault(); run() }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pregunta sobre los documentos de este expediente…" />
        <button type="submit" disabled={busy}>Preguntar</button>
      </form>
      {st.status === 'idle' && (
        <div className="chips ask-ex">{EXAMPLES.map((x) => <button key={x} type="button" className="chip linkchip" onClick={() => { setQ(x); run(x) }}>{x}</button>)}</div>
      )}
      {st.status !== 'idle' && (
        <div className="ask-res">
          <section className="tv-card ask-answer">
            <div className="np-rel">Respuesta {st.model && <span className="muted">· {st.model}{st.ms ? ` · ${(st.ms / 1000).toFixed(1)} s` : ''}</span>}</div>
            {st.status === 'loading' && <div className="muted small"><CircleNotch size={14} className="spinner" /> Buscando en los documentos…</div>}
            {(st.text || st.status === 'writing') && <p className="ask-text">{withCitations(st.text, setLit)}{st.status === 'writing' && <span className="ask-caret" />}</p>}
            {st.note && <div className="muted small">{st.note}</div>}
            {st.status === 'error' && <div className="err">{st.error}</div>}
            {st.info && <Info info={st.info} />}
          </section>
          {st.passages && (
            <section>
              <div className="np-rel">Fragmentos usados <span>{st.passages.length}</span></div>
              {st.passages.map((p, i) => (
                <div key={i} id={`ask-p${i + 1}`} className={`chunk ask-p ${lit === i + 1 ? 'lit' : ''} ${st.cited?.includes(i + 1) ? 'cited' : ''}`}>
                  <div className="chunk-meta">
                    <b>[{i + 1}]</b><span>Doc {p.doc_seq} · {roleEs(p.doc_role)}</span>
                    {p.page_from && <span>pág. {p.page_from}{p.page_to && p.page_to !== p.page_from ? `–${p.page_to}` : ''}</span>}
                    {p.rerank != null && <span className="score" title="Puntuación del reranker">{p.rerank.toFixed(2)}</span>}
                    <button type="button" className="linkish small" onClick={() => go(`/t/${p.tender_id}/d/${p.doc_sha256}?c=${p.chunk_idx}`)}>Abrir en el documento →</button>
                  </div>
                  <p>{p.text}{p.text.length >= 900 ? '…' : ''}</p>
                </div>
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  )
}

// [n] become buttons that light their passage; [F] (the tender's own data) a plain tag.
function withCitations(text, onLight) {
  const out = []
  let last = 0
  for (const m of text.matchAll(/\[(\d+|F)\]/g)) {
    out.push(text.slice(last, m.index))
    const n = m[1]
    out.push(n === 'F'
      ? <span key={m.index} className="cite f" title="Datos del expediente en PLACSP">F</span>
      : <button key={m.index} type="button" className="cite" onMouseEnter={() => onLight(Number(n))} onMouseLeave={() => onLight(null)}
          onClick={() => document.getElementById(`ask-p${n}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })}>{n}</button>)
    last = m.index + m[0].length
  }
  out.push(text.slice(last))
  return out
}

function Info({ info }) {
  return (
    <div className="ask-info small muted">
      {info.hybrid ? 'Significado + palabras clave' : 'Solo significado'} · {info.reranked ? 'reordenado por el reranker' : 'sin reranker'}
      {(info.notes || []).map((n, i) => <div key={i} className="warn-text">{n}</div>)}
    </div>
  )
}
