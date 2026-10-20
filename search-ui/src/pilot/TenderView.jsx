// search-ui/src/pilot/TenderView.jsx — the unified tender: summary, lots, documents in order, questions.
// The head reads title, state and dates, money, authority; the summary the object (what, where,
// how long), guarantees, the timeline (each document previewed on hover) and the record's details.
import { Fragment, useEffect, useState } from 'react'
import { getTender, fileUrl } from './pilotApi.js'
import { CHANNEL, roleEs, shortTitle } from './labels.js'
import { money } from '../format.js'
import { CircleNotch } from '../icons.js'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import NodePanel from './NodePanel.jsx'
import AskView from './AskView.jsx'
import DocHover from './DocHover.jsx'
import SourceHover from './SourceHover.jsx'
import FormulaView from './FormulaView.jsx'
import { guessModel } from './formula.js'
import { go } from './route.js'

const TABS = [['resumen', 'Resumen'], ['lotes', 'Lotes'], ['documentos', 'Documentos'], ['preguntar', 'Preguntar']]

export default function TenderView({ id }) {
  const [state, setState] = useState({ status: 'loading' })
  const [tab, setTab] = useState('resumen')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let live = true
    setState({ status: 'loading' }); setSelected(null)
    getTender(id).then((t) => live && setState({ status: 'done', t })).catch((e) => live && setState({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [id])

  if (state.status === 'loading') return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  if (state.status === 'error') return <div className="err">{state.e}</div>
  const t = state.t

  return (
    <div className="tv">
      <button type="button" className="linkish tv-back" onClick={() => go('')}>← Volver a la búsqueda</button>
      <div className="tv-head">
        <h2 title={t.name}>{shortTitle(t)}</h2>
        {shortTitle(t) !== t.name && <div className="tv-fullname">{t.name}</div>}
        <div className="tv-dates">
          {t.status && <span className={`badge st ${statusClass(t.status)}`}>{t.status}</span>}
          {t.published && <span>Publicado <b>{t.published}</b></span>}
          {t.deadline && <Deadline date={typeof t.deadline === 'string' ? t.deadline : t.deadline.date} />}
        </div>
        <Money value={t.value} budget={typeof t.budget === 'object' ? t.budget?.amount_tax_excl : t.budget} total={t.budget_total} />
        {t.authority && (
          <div className="row">Órgano de contratación: <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(t.authority.id)}`)}>{t.authority.name}</button></div>
        )}
      </div>

      <nav className="tv-tabs">
        {TABS.map(([k, label]) => <button key={k} type="button" className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>)}
        {t.source_url && <a className="tv-src" href={t.source_url} target="_blank" rel="noreferrer">Ver en PLACSP ↗</a>}
      </nav>

      {tab === 'resumen' && <Summary t={t} />}
      {tab === 'lotes' && <Lots t={t} />}
      {tab === 'documentos' && <Documents t={t} onOpen={(sha) => setSelected(`doc:${sha}`)} />}
      {tab === 'preguntar' && <AskView tenderId={t.tender_id} />}
      {selected && <NodePanel id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </div>
  )
}

const STAGE = ['preparación', 'anuncio previo', 'anuncio de licitación', 'pliegos', 'aclaraciones',
  'evaluación', 'propuesta', 'adjudicación', 'formalización', 'ejecución']
const UNIT = { MON: 'meses', ANN: 'años', DAY: 'días', WEE: 'semanas' }
const UNIT1 = { MON: 'mes', ANN: 'año', DAY: 'día', WEE: 'semana' }

function Summary({ t }) {
  const docs = Object.fromEntries((t.documents || []).map((d) => [d.sha256, d]))
  return (
    <div className="tv-sum">
      <div className="tv-sum-main">
        <section className="tv-card">
          <h3>Objeto</h3>
          <p className="tv-desc">{t.description || 'Sin descripción consolidada.'}</p>
          <dl className="tv-facts">
            {(t.cpv || []).length > 0 && (
              <div><dt>CPV</dt><dd>{t.cpv.map((c) => <div key={c} title={c}>{cpvLabel(c) || c}
                {cpvDivision(c) && <span className="muted"> · {cpvDivision(c)}</span>}</div>)}</dd></div>
            )}
            {t.nuts && <div><dt>Lugar</dt><dd title={t.nuts}>{nutsLabel(t.nuts)}</dd></div>}
            {t.duration && <div><dt>Duración</dt><dd>{fmtDuration(t.duration)}{t.extension && <div className="muted small">Prórrogas: {t.extension}</div>}</dd></div>}
          </dl>
          {t.analysable === false && <p className="row">No analizable: {t.skip_reason}</p>}
        </section>
        <section className="tv-card">
          <h3>Garantías y condiciones</h3>
          <ul className="plain">
            {(t.guarantees || []).map((g, i) => <li key={i}>{guaranteeName(g.name)}{g.pct != null && ` · ${g.pct}%`}{g.amount != null && ` · ${money(g.amount)}`}</li>)}
            {(t.execution_conditions || []).map((c, i) => <li key={`c${i}`}>{c.name || c.text}{c.text && c.text !== c.name && <div className="muted small">{c.text}</div>}</li>)}
            {(t.modifications || []).map((m, i) => <li key={`m${i}`}>Modificación {m.name || ''} {m.amount != null && money(m.amount)}</li>)}
            {!(t.guarantees || []).length && !(t.execution_conditions || []).length && !(t.modifications || []).length && <li className="muted">Ninguna publicada.</li>}
          </ul>
        </section>
        <section className="tv-card">
          <h3>Cronología</h3>
          <ol className="timeline">
            {timeline(t).map((e, i) => {
              const d = e.sha256 && docs[e.sha256]
              return (
                <li key={i}><time>{e.date || '—'}</time>
                  {d ? (
                    <DocHover tenderId={t.tender_id} sha={d.sha256}>
                      <button type="button" className="linkish tl-doc" onClick={() => go(`/t/${t.tender_id}/d/${d.sha256}`)}>
                        <span className="chip">{roleEs(d.role)}</span> {d.filename || d.title}
                      </button>
                    </DocHover>
                  ) : <span>{e.event}</span>}
                </li>
              )
            })}
          </ol>
        </section>
      </div>
      <aside className="tv-card tv-ficha">
        <h3>Ficha</h3>
        <dl className="tv-facts">
          {[
            ['ID', t.tender_id], ['Expediente', t.expediente || t.folder_id], ['Canal', CHANNEL[t.channel] || t.channel],
            ['Tipo de contrato', t.contract_type], ['Subtipo', t.subtype], ['Procedimiento', t.procedure],
            ['Regulación armonizada', t.sara == null ? null : t.sara ? 'Sí' : 'No'],
            ['Legislación', t.terms?.national_legislation?.label], ['Financiación', t.terms?.funding?.label],
            ['Variantes', t.terms?.variants_allowed == null ? null : t.terms.variants_allowed ? 'Admitidas' : 'No admitidas'],
            ['Subcontratación', t.subcontracting?.rate_pct != null ? `hasta ${t.subcontracting.rate_pct}%` : t.subcontracting?.text ? 'Ver condiciones' : null],
            ['Lotes', t.counts?.lots], ['Documentos', t.counts?.documents], ['Anuncios', t.counts?.notices],
            ['Fragmentos', t.counts?.chunks?.toLocaleString('es-ES')], ['Entidades', t.counts?.entities],
          ].filter(([, v]) => v != null && v !== '').map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
        {t.source_url && <a className="small" href={t.source_url} target="_blank" rel="noreferrer">Ver en PLACSP ↗</a>}
      </aside>
    </div>
  )
}

// The feed calls the definitive guarantee "Final"; documents already say "Garantía …".
function guaranteeName(name) {
  const n = name === 'Final' ? 'definitiva' : name || ''
  return /^garant/i.test(n) ? n : `Garantía ${n}`
}

// Valor estimado: everything the contract can reach (extensions, modifications, options), no VAT.
// Presupuesto base: the most the authority pays for the base contract, no VAT; the bids' ceiling.
// Without extensions or options they are the same figure, shown once.
function Money({ value, budget, total, inline = false }) {
  const same = value != null && budget != null && Math.abs(value - budget) < 0.5
  const parts = []
  if (same) parts.push(<span key="s" title="Sin prórrogas ni modificaciones previstas, el valor estimado y el presupuesto base coinciden">Presupuesto base y valor estimado <b>{money(budget)}</b></span>)
  else {
    if (budget != null) parts.push(<span key="b" title="Lo máximo que paga el órgano por el contrato base, sin IVA: el techo de las ofertas">Presupuesto base <b>{money(budget)}</b></span>)
    if (value != null) parts.push(<span key="v" title="Todo lo que puede llegar a valer el contrato (prórrogas, modificaciones, opciones), sin IVA">Valor estimado <b>{money(value)}</b></span>)
  }
  if (total != null && budget != null && Math.abs(total - budget) >= 0.5) parts.push(<span key="t" className="muted">{money(total)} con IVA</span>)
  return inline ? <span className="money-inline">{parts}</span> : <div className="money">{parts}</div>
}

function Deadline({ date }) {
  const d = new Date(`${date}T23:59:59`)
  const days = Math.ceil((d - new Date()) / 86400000)
  const left = Number.isNaN(days) ? '' : days > 1 ? `quedan ${days} días` : days === 1 ? 'queda 1 día' : days === 0 ? 'último día' : 'cerrado'
  return <span>Fin de plazo <b>{date}</b>{left && <span className={days >= 0 ? 'dl-open' : 'muted'}> ({left})</span>}</span>
}

// The same document can enter the timeline through several notices: each once, at its first date.
function timeline(t) {
  const seen = new Set()
  return (t.timeline || []).filter((e) => {
    const k = e.sha256 || `${e.date}|${e.event}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

const placeName = (s) => s.replace(/\b([A-ZÁÉÍÓÚÑ'][A-ZÁÉÍÓÚÑ' ]+)\b/g, (w) => (w.length > 3 ? w.charAt(0) + w.slice(1).toLowerCase() : w))

function cpvLabel(code) {
  return (cpvMap[String(code).slice(0, 8)] || '').replace(/\.$/, '')
}
// The division (first two digits) names the sector in words.
function cpvDivision(code) {
  const div = String(code).slice(0, 2).padEnd(8, '0')
  return div !== String(code).slice(0, 8) ? (cpvMap[div] || '').replace(/\.$/, '') : ''
}
function nutsLabel(code) {
  const parent = code.length > 4 && nutsMap[code.slice(0, 4)]          // a province: say its region too
  return [nutsMap[code] || code, parent].filter(Boolean).join(', ')
}
// Open, pending, resolved, void: the colour says where the tender stands.
function statusClass(s) {
  const x = s.toUpperCase()
  if (x.includes('PLAZO') || x.includes('PUBLICAD')) return 'st-open'
  if (x.includes('PENDIENTE') || x.includes('EVALUACI')) return 'st-pending'
  if (x.includes('ANULAD') || x.includes('DESIERT') || x.includes('DESIST') || x.includes('RENUNCIA')) return 'st-void'
  return 'st-done'
}

function fmtDuration(d) {
  if (typeof d !== 'object') return String(d)
  const n = d.amount ?? d.value
  const unit = (n === 1 ? UNIT1 : UNIT)[d.unit] || d.unit_label || d.unit
  const span = [d.start, d.end].filter(Boolean).join(' → ')
  return [n != null ? Number(n).toLocaleString('es-ES') : null, unit].filter((x) => x != null && x !== '').join(' ') + (span ? ` (${span})` : '')
}

function Lots({ t }) {
  const lots = t.lots || []
  const [i, setI] = useState(0)
  if (!lots.length) return <p className="empty">Sin lotes.</p>
  const l = lots[Math.min(i, lots.length - 1)]
  const reqs = l.requirements || []
  return (
    <div className="lv">
      {lots.length > 1 && (
        <nav className="lv-tabs" aria-label="Lotes">
          {lots.map((x, k) => (
            <button key={x.number || k} type="button" className={k === i ? 'on' : ''} title={x.name || ''} onClick={() => setI(k)}>
              Lote {x.number || k + 1}
            </button>
          ))}
        </nav>
      )}
      <section className="tv-card">
        <h3>{l.implicit || lots.length === 1 ? 'Lote único' : `Lote ${l.number}`}{l.name && !/^lote\s*\d*$/i.test(l.name.trim()) && <span className="muted"> · {l.name}</span>}</h3>
        {l.description && <p className="tv-desc">{l.description}</p>}
        <dl className="tv-facts">
          {(l.value != null || l.budget != null) && <div><dt>Importe</dt><dd><Money value={l.value} budget={l.budget} total={l.budget_total} inline /></dd></div>}
          {(l.cpv || []).length > 0 && (
            <div><dt>CPV</dt><dd>{l.cpv.map((c) => <div key={c} title={c}>{cpvLabel(c) || c}
              {cpvDivision(c) && <span className="muted"> · {cpvDivision(c)}</span>}</div>)}</dd></div>
          )}
          {(l.place || l.nuts) && <div><dt>Lugar</dt><dd title={l.nuts || ''}>{l.place ? placeName(l.place) : nutsLabel(l.nuts)}</dd></div>}
          {(l.awarded_to || []).length > 0 && <div><dt>Adjudicataria</dt><dd>{l.awarded_to.map((o) => (
            <button key={o.id} type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(o.id)}`)}>{o.name}</button>))}</dd></div>}
          {l.result?.bids_received != null && <div><dt>Ofertas recibidas</dt><dd>{l.result.bids_received}</dd></div>}
        </dl>
        {(l.bids || []).length > 0 && (
          <ul className="plain lv-bids">
            {l.bids.map((b, k) => (
              <li key={k}>{b.winner ? '🏆 ' : ''}{b.bidders.map((o) => (
                <button key={o.id} type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(o.id)}`)}>{o.name}</button>
              ))}
              {b.price != null && <b> · {money(b.price)}</b>}{b.outcome && <span className="muted"> · {b.outcome}</span>}</li>
            ))}
          </ul>
        )}
      </section>
      {reqs.length > 0 && (
        <section className="tv-card">
          <Requirements reqs={reqs.filter((r) => r.label === 'Requirement')} title="Solvencia y requisitos de participación" />
          <Requirements reqs={reqs.filter((r) => r.label === 'TechnicalRequirement')} title="Requisitos técnicos de la prestación" />
          <Requirements reqs={reqs.filter((r) => !['Requirement', 'TechnicalRequirement'].includes(r.label))} title="Garantías y otras exigencias" />
        </section>
      )}
      <Criteria lot={l} />
    </div>
  )
}

const CRIT_KIND = { JUDGEMENT: 'Juicio de valor', FORMULA: 'Fórmula' }
const CRIT_COLOR = { JUDGEMENT: '#d14d72', FORMULA: '#8b5cf6' }

// Criteria with their weight in the lot's total, each one's source on hover, and its formula
// (from the pipeline, or found in its text) opened below it.
function Criteria({ lot }) {
  const cs = lot.award_criteria || []
  const [open, setOpen] = useState(null)
  if (!cs.length) return null
  const total = cs.reduce((n, c) => n + (c.points || 0), 0)
  const byKind = {}
  for (const c of cs) byKind[c.subtype || 'OTHER'] = (byKind[c.subtype || 'OTHER'] || 0) + (c.points || 0)
  const pct = (p) => (total ? (100 * (p || 0)) / total : 0)
  return (
    <section className="tv-card">
      <h3>Criterios de adjudicación <span className="muted">· {fmtNum(total)} puntos
        {Object.entries(byKind).map(([k, p]) => <span key={k}> · {CRIT_KIND[k] || 'Sin tipo'} {fmtNum(p)} ({fmtNum(pct(p))} %)</span>)}</span></h3>
      {total > 0 && (
        <div className="cr-bar" role="img" aria-label="Peso de cada criterio">
          {cs.filter((c) => c.points).map((c, k) => (
            <span key={k} style={{ width: `${pct(c.points)}%`, background: CRIT_COLOR[c.subtype] || '#94a3b8', opacity: 0.45 + 0.55 * ((k % 3) / 2) }}
              title={`${c.name}: ${fmtNum(c.points)} puntos (${fmtNum(pct(c.points))} %)`} />
          ))}
        </div>
      )}
      <table className="ptable cr-table">
        <thead><tr><th>Criterio</th><th className="num">Puntos</th><th>Peso</th><th /></tr></thead>
        <tbody>
          {cs.map((c, k) => {
            const model = c.formula_model || guessModel([c.detail?.formula, c.formula].filter(Boolean).join('\n'))
            const isOpen = open === k
            return (
              <Fragment key={k}>
                <tr>
                  <td>{c.id ? <SourceHover id={c.id}><span className="cr-name">{c.name}</span></SourceHover> : c.name}
                    {CRIT_KIND[c.subtype] && <span className="cr-kind" style={{ color: CRIT_COLOR[c.subtype] }}> · {CRIT_KIND[c.subtype]}</span>}
                    {c.formula && !c.formula_model && <div className="muted small">{c.formula}</div>}
                    {c.conflicts && <div className="small warn-text">Discrepancia: {Object.entries(c.conflicts).map(([key, vs]) => `${key} ${vs.map((v) => v.value).join(' / ')}`).join('; ')}</div>}</td>
                  <td className="num">{c.points != null ? fmtNum(c.points) : '—'}</td>
                  <td className="cr-w">{c.points ? <><span className="cr-wbar"><i style={{ width: `${pct(c.points)}%`, background: CRIT_COLOR[c.subtype] || '#94a3b8' }} /></span> {fmtNum(pct(c.points))} %</> : null}</td>
                  <td>{model && <button type="button" className="linkish small" onClick={() => setOpen(isOpen ? null : k)}>{isOpen ? 'Ocultar' : 'Ver fórmula'}</button>}</td>
                </tr>
                {isOpen && model && <tr className="cr-fx"><td colSpan={4}><FormulaView model={model} points={c.points} /></td></tr>}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

const fmtNum = (x) => Number(x || 0).toLocaleString('es-ES', { maximumFractionDigits: 1 })

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
            <DocHover tenderId={t.tender_id} sha={d.sha256} className="doc-title">
              <button type="button" className="linkish" onClick={() => go(`/t/${t.tender_id}/d/${d.sha256}`)}>{d.filename || d.title}</button>
            </DocHover>
            {d.summary && <p className="doc-sum">{d.summary}</p>}
            <div className="doc-links">
              <button type="button" className="linkish" onClick={() => go(`/t/${t.tender_id}/d/${d.sha256}`)}>Leer con anotaciones</button>
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
