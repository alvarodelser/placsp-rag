// search-ui/src/pilot/NodePanel.jsx — one graph node: what it is, where it was found, what it connects to.
import { useEffect, useState } from 'react'
import { getNode } from './pilotApi.js'
import { nodeInfo, roleEs } from './labels.js'
import { CircleNotch, X } from '../icons.js'
import { go } from './route.js'

const SKIP = new Set(['id', 'label', 'name', 'title', 'description', 'descriptions', 'evidence', 'summary', 'documents',
  'aliases', 'url', 'sha256', 'source', 'mentions', 'detail', 'conflicts'])
const SOURCE = { feed: 'del feed', documents: 'extraído de documentos', 'feed+documents': 'feed + documentos' }
const DETAIL = {
  threshold_amount: 'Cifra mínima', threshold_unit: 'Unidad', period_years: 'Periodo (años)', reference_base: 'Referencia',
  accreditation: 'Acreditación', standard: 'Norma / certificación', applies_to_lots: 'Lotes', nature: 'Naturaleza',
  mandatory: 'Obligatorio', points: 'Puntos', formula: 'Fórmula', scoring_rule: 'Cómo se puntúa', subcriteria: 'Subcriterios',
  threshold_points: 'Umbral', envelope: 'Sobre', evidence_required: 'Documentación', subtype: 'Tipo',
}

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
  // A reference ("la empresa") is evidence too: counted apart so the reader sees both.
  const refs = d.mentions.filter((m) => m.kind === 'coref').length
  const props = Object.entries(n).filter(([k, v]) => !SKIP.has(k) && v != null && v !== '' && typeof v !== 'object')
  const isOrg = n.label === 'Organization' || n.label === 'JointVenture'
  const evidence = Array.isArray(n.evidence) ? n.evidence : []
  return (
    <div className="np-body">
      <h3>{n.label === 'Document' ? (n.title || n.filename) : (n.name || n.id)}</h3>
      <div className="chips">
        <span className="chip">{SOURCE[n.source] || n.id.split(':')[0]}</span>
        {d.mention_count > 0 && <span className="chip">{d.mention_count} menciones{refs ? ` (${refs} referencias)` : ''}</span>}
        {n.role && <span className="chip">{roleEs(n.role)}</span>}
        {isOrg && <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(n.id)}`)}>Ver en todos los expedientes →</button>}
      </div>
      {(n.description || n.summary) && <p className="np-desc">{n.description || n.summary}</p>}
      {props.length > 0 && (
        <dl className="np-props">
          {props.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}
        </dl>
      )}
      {n.detail && Object.keys(n.detail).length > 0 && (
        <div className="np-sec">
          <div className="np-rel">Detalle extraído</div>
          <dl className="np-props">
            {Object.entries(n.detail).filter(([, v]) => v !== '' && v != null).map(([k, v]) => (
              <div key={k}><dt>{DETAIL[k] || k}</dt><dd>{String(v)}</dd></div>))}
          </dl>
        </div>
      )}
      {n.conflicts && Object.keys(n.conflicts).length > 0 && (
        <div className="np-sec np-warn">
          <div className="np-rel">Discrepancias entre fuentes</div>
          {Object.entries(n.conflicts).map(([k, vs]) => (
            <div key={k} className="small"><b>{DETAIL[k] || k}:</b> {vs.map((v) => `${v.value} (${v.source === 'feed' ? 'feed' : `${v.mentions} menc.`})`).join(' · ')}</div>
          ))}
        </div>
      )}
      {d.mentions.length > 0 && (
        <div className="np-sec">
          <div className="np-rel">Dónde aparece {d.mention_count > d.mentions.length && <span>{d.mentions.length} de {d.mention_count}</span>}</div>
          {d.mentions.map((m, i) => <Mention key={i} m={m} entity={n.id} />)}
        </div>
      )}
      {evidence.length > 0 && d.mentions.length === 0 && (
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
      {d.tender_ids.length > 1 && (
        <div className="np-sec">
          <div className="np-rel">Aparece en {d.tender_ids.length} expedientes</div>
          <div className="chips">{d.tender_ids.map((t) => <button key={t} type="button" className="chip linkchip" onClick={() => go(`/t/${t}`)}>{t}</button>)}</div>
        </div>
      )}
    </div>
  )
}

function Mention({ m, entity }) {
  return (
    <div className={`mention ${m.kind === 'coref' ? 'is-ref' : ''}`}>
      <div className="chunk-meta">
        <span>Doc {m.doc_seq ?? '?'} · {roleEs(m.doc_role)}</span>
        {m.page && <span>pág. {m.page}</span>}
        {m.kind === 'coref' && <span className="chip" title="Expresión que se refiere a la entidad sin nombrarla">referencia «{m.surface}»</span>}
        {!m.located && <span title="La cita no se encontró literal en el texto">cita aproximada</span>}
        {m.doc_sha256 && <button type="button" className="linkish small" onClick={() =>
          go(`/t/${m.tender_id}/d/${m.doc_sha256}?c=${m.chunk_idx}&e=${encodeURIComponent(entity)}`)}>ver en el documento →</button>}
      </div>
      <p>{m.before && '…'}{m.before}<mark>{m.quote}</mark>{m.after}{m.after && '…'}</p>
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
