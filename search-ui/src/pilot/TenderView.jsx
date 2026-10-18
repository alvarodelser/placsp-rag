// search-ui/src/pilot/TenderView.jsx — the unified tender: summary, lots, documents in order, graph, questions.
import { useEffect, useState } from 'react'
import { getTender, getTenderGraph, fileUrl } from './pilotApi.js'
import { CHANNEL, COMPANY_ROLE, roleEs } from './labels.js'
import { money } from '../format.js'
import { CircleNotch } from '../icons.js'
import GraphView from './GraphView.jsx'
import NodePanel from './NodePanel.jsx'
import AskView from './AskView.jsx'
import { go } from './route.js'

const TABS = [['resumen', 'Resumen'], ['lotes', 'Lotes'], ['documentos', 'Documentos'], ['grafo', 'Grafo'], ['preguntar', 'Preguntar']]

export default function TenderView({ id }) {
  const [state, setState] = useState({ status: 'loading' })
  const [tab, setTab] = useState('resumen')
  const [graph, setGraph] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let live = true
    setState({ status: 'loading' }); setGraph(null); setSelected(null)
    getTender(id).then((t) => live && setState({ status: 'done', t })).catch((e) => live && setState({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [id])
  useEffect(() => {
    if (tab !== 'grafo' || graph) return
    getTenderGraph(id).then(setGraph).catch((e) => setGraph({ error: e.message }))
  }, [tab, id, graph])

  if (state.status === 'loading') return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  if (state.status === 'error') return <div className="err">{state.e}</div>
  const t = state.t

  return (
    <div className="tv">
      <div className="tv-head">
        <div className="badges">
          <span className="badge">{CHANNEL[t.channel] || t.channel}</span>
          {t.status && <span className="badge estado">{t.status}</span>}
          {t.contract_type && <span className="badge">{t.contract_type}</span>}
          {t.procedure && <span className="badge">{t.procedure}</span>}
          {t.analysable === false && <span className="badge warn" title={t.skip_reason}>no analizable</span>}
        </div>
        <h2>{t.name}</h2>
        <div className="row">
          {t.authority && <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(t.authority.id)}`)}>{t.authority.name}</button>}
          {t.expediente && <> · Exp. <b>{t.expediente}</b></>} · ID <b>{t.tender_id}</b>
        </div>
        <div className="money">
          {t.value != null && <span>Valor estimado <b>{money(t.value)}</b></span>}
          {t.budget != null && <span>Presupuesto <b>{money(typeof t.budget === 'object' ? t.budget.amount_tax_excl : t.budget)}</b></span>}
          {t.published && <span>Publicado <b>{t.published}</b></span>}
          {t.deadline && <span>Fin de plazo <b>{typeof t.deadline === 'string' ? t.deadline : t.deadline.date}</b></span>}
        </div>
        <div className="tv-counts">
          {Object.entries(t.counts || {}).map(([k, v]) => <span key={k}><b>{v}</b> {COUNT[k] || k}</span>)}
        </div>
      </div>

      <nav className="tv-tabs">
        {TABS.map(([k, label]) => <button key={k} type="button" className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>)}
        {t.source_url && <a className="tv-src" href={t.source_url} target="_blank" rel="noreferrer">Ver en PLACSP ↗</a>}
      </nav>

      {tab === 'resumen' && <Summary t={t} />}
      {tab === 'lotes' && <Lots t={t} />}
      {tab === 'documentos' && <Documents t={t} onOpen={(sha) => setSelected(`doc:${sha}`)} />}
      {tab === 'grafo' && (
        graph == null ? <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
          : graph.error ? <div className="err">{graph.error}</div>
            : <GraphView graph={graph} selected={selected} onSelect={setSelected} />
      )}
      {tab === 'preguntar' && <AskView tenderId={t.tender_id} />}
      {selected && <NodePanel id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </div>
  )
}

const STAGE = ['preparación', 'anuncio previo', 'anuncio de licitación', 'pliegos', 'aclaraciones',
  'evaluación', 'propuesta', 'adjudicación', 'formalización', 'ejecución']
const UNIT = { MON: 'meses', ANN: 'años', DAY: 'días', WEE: 'semanas' }
const COUNT = { lots: 'lotes', documents: 'documentos', notices: 'anuncios', chunks: 'fragmentos', entities: 'entidades', relations: 'relaciones' }

function Summary({ t }) {
  return (
    <div className="tv-grid">
      <section className="tv-card wide">
        <h3>Descripción del expediente</h3>
        <p className="tv-desc">{t.description || 'Sin descripción consolidada.'}</p>
        <div className="chips">
          {(t.cpv || []).map((c) => <span key={c} className="chip">CPV {c}</span>)}
          {t.nuts && <span className="chip">NUTS {t.nuts}</span>}
          {t.duration && <span className="chip">Duración {fmtDuration(t.duration)}</span>}
        </div>
        {t.analysable === false && <p className="row">No analizable: {t.skip_reason}</p>}
      </section>
      <section className="tv-card">
        <h3>Empresas</h3>
        {(t.companies || []).length === 0 ? <p className="row">Ninguna identificada.</p> : (
          <ul className="plain">
            {t.companies.map((c) => (
              <li key={c.id}>
                <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(c.id)}`)}>{c.name}</button>
                {c.nif && <span className="muted"> · {c.nif}</span>}
                <div className="chips">{c.roles.map((r) => <span key={r} className={`chip role-${r}`}>{COMPANY_ROLE[r] || r}</span>)}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="tv-card">
        <h3>Garantías y condiciones</h3>
        <ul className="plain">
          {(t.guarantees || []).map((g, i) => <li key={i}>Garantía {g.name}{g.pct != null && ` · ${g.pct}%`}{g.amount != null && ` · ${money(g.amount)}`}</li>)}
          {(t.execution_conditions || []).map((c, i) => <li key={`c${i}`}>{c.name || c.text}</li>)}
          {(t.modifications || []).map((m, i) => <li key={`m${i}`}>Modificación {m.name || ''} {m.amount != null && money(m.amount)}</li>)}
          {!(t.guarantees || []).length && !(t.execution_conditions || []).length && !(t.modifications || []).length && <li className="muted">Ninguna publicada.</li>}
        </ul>
      </section>
      <section className="tv-card wide">
        <h3>Cronología</h3>
        <ol className="timeline">
          {(t.timeline || []).map((e, i) => <li key={i}><time>{e.date || '—'}</time><span>{e.event}</span></li>)}
        </ol>
      </section>
    </div>
  )
}

function fmtDuration(d) {
  if (typeof d !== 'object') return String(d)
  return [d.amount ?? d.value, UNIT[d.unit] || d.unit_label || d.unit].filter(Boolean).join(' ')
}

function Lots({ t }) {
  const lots = t.lots || []
  if (!lots.length) return <p className="empty">Sin lotes.</p>
  return (
    <div className="lots">
      {lots.map((l) => (
        <details key={l.number || l.name} className="tv-card lot" open={lots.length <= 3}>
          <summary>
            <b>{l.number ? `Lote ${l.number}` : 'Lote único'}</b> {l.name && l.name !== l.number && <span>· {l.name}</span>}
            {l.budget != null && <span className="muted"> · {money(l.budget)}</span>}
            {(l.awarded_to || []).length > 0 && <span className="chip role-winner">{l.awarded_to.map((o) => o.name).join(', ')}</span>}
          </summary>
          {l.description && <p className="tv-desc">{l.description}</p>}
          {(l.award_criteria || []).length > 0 && (
            <>
              <h4>Criterios de adjudicación {l.criteria_points_total != null && <span className="muted">· {l.criteria_points_total} puntos</span>}</h4>
              <table className="ptable">
                <thead><tr><th>Criterio</th><th>Tipo</th><th>Puntos</th><th>Origen</th></tr></thead>
                <tbody>
                  {l.award_criteria.map((c, i) => (
                    <tr key={i}>
                      <td>{c.name}{c.formula && <div className="muted small">{c.formula}</div>}
                        {c.conflicts && <div className="small warn-text">Discrepancia: {Object.entries(c.conflicts).map(([k, vs]) => `${k} ${vs.map((v) => v.value).join(' / ')}`).join('; ')}</div>}</td>
                      <td>{c.subtype === 'JUDGEMENT' ? 'Juicio de valor' : c.subtype === 'FORMULA' ? 'Fórmula' : c.subtype || '—'}</td>
                      <td className="num">{c.points ?? '—'}</td>
                      <td>{{ feed: 'feed', documents: 'documentos', 'feed+documents': 'feed + docs' }[c.source] || c.source}{c.mentions ? ` · ${c.mentions} menc.` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <Requirements reqs={(l.requirements || []).filter((r) => r.label === 'Requirement')} title="Solvencia y requisitos de participación" />
          <Requirements reqs={(l.requirements || []).filter((r) => r.label === 'TechnicalRequirement')} title="Requisitos técnicos de la prestación" />
          <Requirements reqs={(l.requirements || []).filter((r) => !['Requirement', 'TechnicalRequirement'].includes(r.label))} title="Garantías y otras exigencias" />
          {((l.bids || []).length > 0 || l.result) && (
            <>
              <h4>Resultado {l.result?.bids_received != null && <span className="muted">· {l.result.bids_received} ofertas recibidas</span>}</h4>
              <ul className="plain">
                {(l.bids || []).map((b, i) => (
                  <li key={i}>{b.winner ? '🏆 ' : ''}{b.bidders.map((o) => (
                    <button key={o.id} type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(o.id)}`)}>{o.name}</button>
                  ))}
                  {b.price != null && <b> · {money(b.price)}</b>}{b.outcome && <span className="muted"> · {b.outcome}</span>}</li>
                ))}
              </ul>
            </>
          )}
        </details>
      ))}
    </div>
  )
}

function Requirements({ reqs, title }) {
  if (!reqs.length) return null
  // Requirements a feed line points to ("según cláusula 8ª") are listed under that line.
  const byId = Object.fromEntries(reqs.map((r) => [r.id, r]))
  const nested = new Set(reqs.flatMap((r) => r.detailed_by || []))
  const item = (r, child = false) => (
    <li key={r.id || r.name} className={child ? 'req-child' : ''}>
      <span className="chip">{r.detail?.subtype || r.subtype || r.label}</span> {r.name || r.text}
      {r.amount != null && <b> · {money(r.amount)}</b>}
      {r.detail?.threshold_amount != null && <b> · {r.detail.threshold_amount} {r.detail.threshold_unit || ''}{r.detail.period_years ? ` (${r.detail.period_years} años)` : ''}</b>}
      {r.source === 'feed' && <span className="muted small"> · feed</span>}
      {(r.qualifications || []).length > 0 && <span className="muted"> · acredita: {r.qualifications.join(', ')}</span>}
      {r.description && <div className="muted small">{r.description}</div>}
      {(r.detailed_by || []).length > 0 && (
        <ul className="plain req-children">{r.detailed_by.map((id) => byId[id] && item(byId[id], true))}</ul>
      )}
    </li>
  )
  return (
    <>
      <h4>{title}</h4>
      <ul className="plain">{reqs.filter((r) => !nested.has(r.id)).map((r) => item(r))}</ul>
    </>
  )
}

function Documents({ t, onOpen }) {
  const docs = t.documents || []
  return (
    <ol className="docs">
      {docs.map((d) => (
        <li key={d.sha256} className="tv-card doc">
          <div className="doc-seq">{d.seq}</div>
          <div className="doc-main">
            <div className="doc-meta">
              <span className="chip">{roleEs(d.role)}</span>
              <time title={`fecha: ${d.date_source}`}>{d.effective_date || 'sin fecha'}</time>
              <span className="muted">{STAGE[d.stage]}</span>
              {d.chars ? <span className="muted">{Math.round(d.chars / 1000)}k caracteres</span> : null}
              {d.ner_chunks ? <span className="muted">{d.ner_chunks} fragmentos</span> : null}
              {d.entities ? <span className="muted">{d.entities} entidades</span> : null}
            </div>
            <div className="doc-title">{d.title || d.filename}</div>
            {d.summary && <p className="doc-sum">{d.summary}</p>}
            <div className="doc-links">
              <button type="button" className="linkish" onClick={() => onOpen(d.sha256)}>Entidades y relaciones</button>
              {d.stored && <a href={fileUrl(d.sha256)} target="_blank" rel="noreferrer">Archivo guardado</a>}
              {d.url && <a href={d.url} target="_blank" rel="noreferrer">Original ↗</a>}
              <span className="muted mono" title={d.sha256}>{d.sha256.slice(0, 10)}</span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
