// search-ui/src/pilot/AskView.jsx — questions over one tender's documents, answered with citations.
// The passages come first (meaning + keywords, reordered by a reranker); the answer streams in as
// a small model writes it from them, each claim citing [n]. The reader sees one source at a time:
// the claim it backs is lit, its sentence quoted, its place named on a pill. The other sources
// wait on their pills (the first few; the rest behind "+N"), the uncited passages behind a fold.
import { useEffect, useRef, useState } from 'react'
import { answer } from './pilotApi.js'
import { roleEs } from './labels.js'
import { claims, sources, sourceOf, excerpt } from './cites.js'
import { LoaderCircle, ArrowRight, ChevronRight } from '../icons.js'
import { go } from './route.js'

const EXAMPLES = ['¿Qué solvencia económica se exige?', '¿Cuál es la garantía definitiva?', '¿Cómo se valora el precio?',
  '¿Qué penalidades hay por incumplimiento?', '¿Se permite subcontratar?', '¿Qué equipo mínimo se exige?']
const PILLS = 3

export default function AskView({ t }) {
  const [q, setQ] = useState('')
  const [turns, setTurns] = useState([])
  const abort = useRef(null)
  const end = useRef(null)
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [turns.length])

  async function run(query = q) {
    query = query.trim()
    if (!query) return
    abort.current?.abort()
    const ctl = new AbortController()
    abort.current = ctl
    setQ('')
    const id = Date.now()
    const set = (f) => setTurns((ts) => ts.map((x) => (x.id === id ? f(x) : x)))
    setTurns((ts) => [...ts.map((x) => (x.status === 'loading' || x.status === 'writing' ? { ...x, status: 'stopped' } : x)),
      { id, q: query, status: 'loading', text: '', passages: null }])
    try {
      await answer({ q: query, tender_id: t.tender_id }, (e) => set((s) => {
        if (e.type === 'passages') return { ...s, passages: e.passages, info: e.info, model: e.model, status: 'writing' }
        if (e.type === 'token') return { ...s, text: s.text + e.text }
        if (e.type === 'done') return { ...s, status: 'done', text: e.text || s.text, ms: e.ms, note: e.note }
        if (e.type === 'error') return { ...s, status: 'error', error: e.error }
        return s
      }), ctl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') set((s) => ({ ...s, status: 'error', error: e.message }))
    }
  }

  const busy = turns.some((x) => x.status === 'loading' || x.status === 'writing')
  return (
    <div className="ask">
      <div className="ask-card">
        <div className="ask-body">
          {turns.length === 0 && (
            <div className="ask-empty">
              <div className="chips">{EXAMPLES.map((x) => <button key={x} type="button" className="chip linkchip" onClick={() => run(x)}>{x}</button>)}</div>
            </div>
          )}
          {turns.map((x) => <Turn key={x.id} turn={x} />)}
          <div ref={end} />
        </div>
        <form className="pbar ask-form" onSubmit={(e) => { e.preventDefault(); run() }}>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pregunta sobre los documentos de este expediente…" />
          <button type="submit" disabled={busy || !q.trim()}>Preguntar</button>
        </form>
      </div>
    </div>
  )
}

function Turn({ turn }) {
  const ps = turn.passages || []
  const parts = claims(turn.text, ps.length)
  const srcs = sources(parts, ps)
  const [sel, setSel] = useState(null)              // { src, claim } the reader chose; else the first source
  const [more, setMore] = useState(false)
  const src = srcs.find((s) => s.key === sel?.src) || srcs[0]
  const claimIdx = sel?.claim ?? parts.findIndex((p) => p.refs?.some((r) => src?.nums.includes(r)))
  const writing = turn.status === 'writing'

  const pick = (s, claim) => setSel({ src: s.key, claim: claim ?? parts.findIndex((p) => p.refs?.some((r) => s.nums.includes(r))) })
  const shown = more ? srcs : srcs.slice(0, PILLS).concat(srcs.indexOf(src) >= PILLS ? [src] : [])
  const hidden = srcs.length - shown.length

  return (
    <div className="ask-turn">
      <div className="ask-q">{turn.q}</div>
      {turn.status === 'loading' && <div className="ask-wait"><LoaderCircle size={14} className="spinner" /> Buscando en los documentos…</div>}
      {(turn.text || writing) && (
        <p className="ask-a">
          {parts.map((p, i) => !p.refs ? p.text : (
            <span key={i} className={`claim ${i === claimIdx ? 'on' : ''}`} onMouseEnter={() => pick(sourceOf(srcs, p.refs[0]), i)}
              onClick={() => pick(sourceOf(srcs, p.refs[0]), i)}>
              {p.text}
              <sup>{[...new Set(p.refs.map((r) => sourceOf(srcs, r).num))].join(',')}</sup>
            </span>
          ))}
          {writing && <span className="ask-caret" />}
        </p>
      )}
      {src && <Quote src={src} claim={parts[claimIdx]?.text || ''} />}
      {srcs.length > 0 && (
        <div className="ask-pills">
          {shown.map((s) => <Pill key={s.key} s={s} on={s === src} onPick={() => pick(s)} />)}
          {hidden > 0 && <button type="button" className="ask-pill ask-pill-more" onClick={() => setMore(true)}>+{hidden} {hidden === 1 ? 'fuente' : 'fuentes'}</button>}
        </div>
      )}
      {turn.status === 'done' && turn.text.trim() && !srcs.length && <div className="ask-note warn-text">La respuesta no cita ningún fragmento.</div>}
      {turn.note && <div className="ask-note">{turn.note}</div>}
      {turn.status === 'stopped' && <div className="ask-note">Interrumpida por la pregunta siguiente.</div>}
      {turn.status === 'error' && <div className="err">{turn.error}</div>}
      {(turn.info?.notes || []).map((n, i) => <div key={i} className="ask-note warn-text">{n}</div>)}
      {ps.length > 0 && <Consulted turn={turn} srcs={srcs} />}
    </div>
  )
}

function place(s) {
  const p = s.passage
  if (!p) return { doc: 'PLACSP', rest: ['datos del expediente'] }
  const pg = p.page_from ? `pág. ${p.page_from}${p.page_to && p.page_to !== p.page_from ? `–${p.page_to}` : ''}` : null
  return { doc: p.doc_role ? roleEs(p.doc_role) : `Doc ${p.doc_seq}`, rest: [pg].filter(Boolean) }
}

function Pill({ s, on, onPick }) {
  const { doc, rest } = place(s)
  return (
    <button type="button" className={`ask-pill ${on ? 'on' : ''}`} title={s.passage?.doc_title || 'Datos publicados en PLACSP'}
      onMouseEnter={onPick} onClick={onPick}>
      <sup>{s.num}</sup><b>{doc}</b>{rest.map((x) => <span key={x}>{x}</span>)}
    </button>
  )
}

function Quote({ src, claim }) {
  if (!src.passage) return <blockquote className="ask-quote f">Datos del expediente en PLACSP.</blockquote>
  const p = src.passage
  const ex = excerpt(p.text, claim)
  return (
    <blockquote className="ask-quote">
      «{ex.text}»
      <button type="button" className="linkish" onClick={() => go(`/t/${p.tender_id}/d/${p.doc_sha256}?c=${p.chunk_idx}`)}>Abrir en el documento <ArrowRight size={13} className="ico" /></button>
    </blockquote>
  )
}

// Every passage the answer was written from, folded: the cited ones first, with their source number.
function Consulted({ turn, srcs }) {
  const ps = turn.passages
  const num = (i) => sourceOf(srcs, i + 1)?.num
  const order = ps.map((p, i) => i).sort((a, b) => (num(a) ?? 99) - (num(b) ?? 99))
  const info = turn.info
  return (
    <details className="ask-more">
      <summary><ChevronRight size={13} className="ico ask-more-chev" />{ps.length} fragmentos consultados{srcs.length ? ` · ${srcs.filter((s) => s.passage).length} citados` : ''}</summary>
      {order.map((i) => {
        const p = ps[i]
        return (
          <div key={i} className={`chunk ask-p ${num(i) ? 'cited' : ''}`}>
            <div className="chunk-meta">
              {num(i) ? <b>{num(i)}</b> : <span className="muted">—</span>}
              <span>{roleEs(p.doc_role)} · Doc {p.doc_seq}</span>
              {p.page_from && <span>pág. {p.page_from}{p.page_to && p.page_to !== p.page_from ? `–${p.page_to}` : ''}</span>}
              {p.rerank != null && <span className="score" title="Puntuación del reranker">{p.rerank.toFixed(2)}</span>}
              <button type="button" className="linkish small" onClick={() => go(`/t/${p.tender_id}/d/${p.doc_sha256}?c=${p.chunk_idx}`)}>Abrir <ArrowRight size={13} className="ico" /></button>
            </div>
            <p>{p.text}{p.text.length >= 900 ? '…' : ''}</p>
          </div>
        )
      })}
      {info && (
        <div className="ask-note">
          {info.hybrid ? 'Significado + palabras clave' : 'Solo significado'} · {info.reranked ? 'reordenado por el reranker' : 'sin reranker'}
          {turn.model && ` · ${turn.model}`}{turn.ms ? ` · ${(turn.ms / 1000).toFixed(1)} s` : ''}
        </div>
      )}
    </details>
  )
}
