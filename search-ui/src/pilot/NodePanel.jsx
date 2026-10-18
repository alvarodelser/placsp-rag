// search-ui/src/pilot/NodePanel.jsx — one graph node: what it is, where it was found, what it connects to.
import { useEffect, useState } from 'react'
import { getNode } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { CircleNotch, X } from '../icons.js'
import { go } from './route.js'

const SKIP = new Set(['id', 'label', 'name', 'title', 'description', 'descriptions', 'evidence', 'summary', 'documents',
  'aliases', 'url', 'sha256', 'source'])

export default function NodePanel({ id, onSelect, onClose }) {
  const [state, setState] = useState({ status: 'loading' })
  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    getNode(id).then((d) => live && setState({ status: 'done', d })).catch((e) => live && setState({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [id])

  return (
    <aside className="np">
      <div className="np-head">
        <span className="np-kind" style={{ color: nodeInfo(state.d?.node.label).color }}>{nodeInfo(state.d?.node.label).es}</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Cerrar"><X size={16} /></button>
      </div>
      {state.status === 'loading' && <div className="loading-state"><CircleNotch size={22} className="spinner" /></div>}
      {state.status === 'error' && <div className="err">{state.e}</div>}
      {state.status === 'done' && <Body d={state.d} onSelect={onSelect} />}
    </aside>
  )
}

function Body({ d, onSelect }) {
  const n = d.node
  const props = Object.entries(n).filter(([k, v]) => !SKIP.has(k) && v != null && v !== '' && typeof v !== 'object')
  const isOrg = n.label === 'Organization' || n.label === 'JointVenture'
  const evidence = Array.isArray(n.evidence) ? n.evidence : []
  return (
    <div className="np-body">
      <h3>{n.label === 'Document' ? (n.title || n.filename) : (n.name || n.id)}</h3>
      <div className="chips">
        <span className="chip">{n.source === 'document' ? 'extraído de documentos' : n.source === 'feed' ? 'del feed' : n.id.split(':')[0]}</span>
        {n.role && <span className="chip">{roleEs(n.role)}</span>}
        {isOrg && <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(n.id)}`)}>Ver en todos los expedientes →</button>}
      </div>
      {(n.description || n.summary) && <p className="np-desc">{n.description || n.summary}</p>}
      {props.length > 0 && (
        <dl className="np-props">
          {props.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}
        </dl>
      )}
      {evidence.length > 0 && (
        <details className="np-sec"><summary>Evidencia ({evidence.length})</summary>
          {evidence.slice(0, 6).map((e, i) => <blockquote key={i}>{e}</blockquote>)}
        </details>
      )}
      {Object.entries(d.neighbours).map(([rel, list]) => (
        <div key={rel} className="np-sec">
          <div className="np-rel">{rel} <span>{list.length}</span></div>
          <ul className="np-list">
            {list.slice(0, 25).map((m) => (
              <li key={m.id}><button type="button" className="linkish" onClick={() => onSelect(m.id)}>
                <i style={{ background: nodeInfo(m.label).color }} />{m.label === 'Document' ? `${roleEs(m.role)} · ${m.title || m.filename}` : (m.name || m.id)}
                {m.points != null && <b> · {m.points} pts</b>}
              </button></li>
            ))}
          </ul>
        </div>
      ))}
      {d.mentions.length > 0 && (
        <div className="np-sec">
          <div className="np-rel">Fragmentos que lo mencionan</div>
          {d.mentions.map((c, i) => <Chunk key={i} c={c} />)}
        </div>
      )}
      {d.tender_ids.length > 1 && (
        <div className="np-sec">
          <div className="np-rel">Aparece en {d.tender_ids.length} expedientes</div>
          <div className="chips">{d.tender_ids.map((t) => <button key={t} type="button" className="chip linkchip" onClick={() => go(`/t/${t}`)}>{t}</button>)}</div>
        </div>
      )}
    </div>
  )
}

export function Chunk({ c, showTender = false }) {
  const pages = c.page_from ? (c.page_to && c.page_to !== c.page_from ? `págs. ${c.page_from}–${c.page_to}` : `pág. ${c.page_from}`) : null
  return (
    <div className="chunk">
      <div className="chunk-meta">
        {showTender && <button type="button" className="linkish" onClick={() => go(`/t/${c.tender_id}`)}>{c.tender_id}</button>}
        <span>Doc {c.doc_seq} · {roleEs(c.doc_role)}</span>{pages && <span>{pages}</span>}
        {c.score != null && <span className="score">{c.score}</span>}
      </div>
      <div className="chunk-title">{c.doc_title}</div>
      <p>{c.text.length > 600 ? `${c.text.slice(0, 600)}…` : c.text}</p>
    </div>
  )
}
