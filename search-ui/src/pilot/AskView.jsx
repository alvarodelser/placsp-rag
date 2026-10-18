// search-ui/src/pilot/AskView.jsx — GraphRAG retrieval: passages, entities and their graph context.
// No generated answer: what comes back is exactly what a generator would be given.
import { useEffect, useState } from 'react'
import { ask } from './pilotApi.js'
import { nodeInfo, CHANNEL } from './labels.js'
import { CircleNotch } from '../icons.js'
import { Chunk } from './NodePanel.jsx'
import { go } from './route.js'

const EXAMPLES = ['solvencia económica volumen anual de negocios', 'criterios evaluables mediante juicio de valor',
  'penalidades por incumplimiento', 'subcontratación', 'equipo mínimo y titulaciones exigidas']

export default function AskView({ tenderId = '', initial = '' }) {
  const [q, setQ] = useState(initial)
  const [state, setState] = useState({ status: 'idle' })

  async function run(query = q) {
    if (!query.trim()) return
    setState({ status: 'loading' })
    try {
      setState({ status: 'done', d: await ask({ q: query.trim(), tender_id: tenderId, k: 10 }) })
    } catch (e) {
      setState({ status: 'error', e: e.message })
    }
  }
  useEffect(() => { if (initial) run(initial) }, [initial]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="ask">
      <form onSubmit={(e) => { e.preventDefault(); if (!tenderId) go(`/ask?q=${encodeURIComponent(q)}`); run() }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder={tenderId ? 'Pregunta sobre este expediente…' : 'Pregunta sobre todos los expedientes del piloto…'} />
        <button type="submit" disabled={state.status === 'loading'}>Buscar</button>
      </form>
      {state.status === 'idle' && (
        <div className="chips ask-ex">{EXAMPLES.map((x) => <button key={x} type="button" className="chip linkchip" onClick={() => { setQ(x); run(x) }}>{x}</button>)}</div>
      )}
      {state.status === 'loading' && <div className="loading-state"><CircleNotch size={26} className="spinner" /></div>}
      {state.status === 'error' && <div className="err">{state.e}</div>}
      {state.status === 'done' && (
        <div className="ask-grid">
          <section>
            <h3>Fragmentos</h3>
            {state.d.chunks.length === 0 && <p className="muted">Ninguno.</p>}
            {state.d.chunks.map((c, i) => <Chunk key={i} c={c} showTender={!tenderId} />)}
          </section>
          <section>
            <h3>Entidades del grafo</h3>
            {state.d.entities.map((e) => (
              <div key={e.id} className="tv-card ent">
                <div className="ent-head"><i style={{ background: nodeInfo(e.label).color }} />{nodeInfo(e.label).es}<span className="score">{e.score}</span></div>
                <b>{e.name}</b>
                {e.description && <p className="small">{e.description}</p>}
                {e.context.length > 0 && (
                  <ul className="ctx">
                    {e.context.map((c, i) => <li key={i}><span className="muted">{c.out ? c.rel : `← ${c.rel}`}</span> {c.node.name || c.node.title || c.node.id}</li>)}
                  </ul>
                )}
                {!tenderId && e.tender_ids.length > 0 && (
                  <div className="chips">{e.tender_ids.slice(0, 6).map((t) => <button key={t} type="button" className="chip linkchip" onClick={() => go(`/t/${t}`)}>{t}</button>)}</div>
                )}
              </div>
            ))}
            {!tenderId && state.d.tenders.length > 0 && (
              <>
                <h3>Expedientes</h3>
                {state.d.tenders.map((t) => (
                  <button key={t.tender_id} type="button" className="mini" onClick={() => go(`/t/${t.tender_id}`)}>
                    <span className="badge">{CHANNEL[t.channel] || t.channel}</span> {t.name}
                  </button>
                ))}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
