// search-ui/src/pilot/TenderView.jsx — the unified tender: summary, lots, documents in order, questions.
// The head reads title (id on hover), authority and money (figures on hover), state and dates; the summary the object (what, where,
// how long), guarantees, the timeline (each document previewed on hover) and the record's details.
import { Fragment, useEffect, useMemo, useState } from 'react'
import { getTender } from './pilotApi.js'
import { CHANNEL, dmy, docDateTip, nodeInfo, roleEs, shortTitle, tenderState } from './labels.js'
import Tip from './Tip.jsx'
import { money } from '../format.js'
import { Trophy } from '../icons.js'
import { ErrorNote, ExtLink, Loading, Tabs } from './ui.jsx'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import NodePanel from './NodePanel.jsx'
import AskView from './AskView.jsx'
import DocHover from './DocHover.jsx'
import SourceHover from './SourceHover.jsx'
import FormulaView, { Tex, freeSymbols, parseModel, startValues } from './FormulaView.jsx'
import { evaluate, guessModel, symbolTex } from './formula.js'
import { go } from './route.js'

const TABS = [['resumen', 'Resumen'], ['lotes', 'Lotes'], ['documentos', 'Documentos'], ['preguntar', 'Preguntar']]

export default function TenderView({ id }) {
  const [state, setState] = useState({ status: 'loading' })
  const [tab, setTab] = useState('resumen')

  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    getTender(id).then((t) => live && setState({ status: 'done', t })).catch((e) => live && setState({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [id])

  if (state.status === 'loading') return <Loading size={26} />
  if (state.status === 'error') return <ErrorNote>{state.e}</ErrorNote>
  const t = state.t

  return (
    <div className="tv">
      <div className="tv-head">
        <div className="hp tv-title" tabIndex={0}>
          <div className="tv-kicker"><span className="chip">{CHANNEL[t.channel] || t.channel || 'Expediente'}</span>
            {(t.expediente || t.folder_id) && <span className="mono">{t.expediente || t.folder_id}</span>}</div>
          <h2>{shortTitle(t)}</h2>
          {shortTitle(t) !== t.name && <div className="tv-fullname">{t.name}</div>}
          <div className="hp-card">
            <div><span>ID</span><b>{t.tender_id}</b></div>
            {(t.expediente || t.folder_id) && <div><span>Expediente</span><b>{t.expediente || t.folder_id}</b></div>}
          </div>
        </div>
        <div className="tv-mid">
          {t.authority && (
            <div className="tv-auth">
              <span className="tv-lbl">Órgano de contratación</span>
              <button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(t.authority.id)}`)}>{t.authority.name}</button>
            </div>
          )}
          <HeadMoney value={t.value} budget={typeof t.budget === 'object' ? t.budget?.amount_tax_excl : t.budget} />
        </div>
        <Period t={t} />
      </div>

      <Tabs items={TABS} value={tab} onChange={setTab} extra={<ExtLink href={t.source_url}>Ver en PLACSP</ExtLink>} />

      {tab === 'resumen' && <Summary t={t} />}
      {tab === 'lotes' && <Lots t={t} />}
      {tab === 'documentos' && <Documents t={t} />}
      {tab === 'preguntar' && <AskView t={t} />}
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
                <li key={i}><time>{dmy(e.date) || '—'}</time>
                  {d ? (
                    <DocHover tenderId={t.tender_id} sha={d.sha256}>
                      <button type="button" className="linkish tl-doc" onClick={() => go(`/t/${t.tender_id}/d/${d.sha256}`)}>
                        <span className="chip">{roleEs(d.role)}</span><span>{d.filename || d.title}</span>
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
        <ExtLink href={t.source_url} className="small">Ver en PLACSP</ExtLink>
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
// A lot's amount: the figure alone; what each figure is, on hover.
function Money({ value, budget }) {
  const head = budget ?? value
  if (head == null) return null
  const rows = [budget != null && ['Presupuesto base sin IVA', budget], value != null && ['Valor estimado', value]].filter(Boolean)
  return <Tip tip={<span className="tip-rows">{rows.map(([k, v]) => <span key={k}>{k} <b>{money(v)}</b></span>)}</span>}><b>{money(head)}</b></Tip>
}

// The headline figure is the bids' ceiling (presupuesto base) when there is one; the hover card
// gives every figure the record has, each with what it means.
function HeadMoney({ value, budget }) {
  const head = budget ?? value
  if (head == null) return null
  const rows = []
  if (budget != null) rows.push(['Presupuesto base sin IVA', budget])
  if (value != null) rows.push(['Valor estimado', value])
  return (
    <div className="hp tv-money" tabIndex={0}>
      <b>{money(head)}</b>
      <div className="hp-card right">
        {rows.map(([k, v]) => <div key={k} className="hp-money"><span>{k}</span><b>{money(v)}</b></div>)}
      </div>
    </div>
  )
}

// One line for where the tender stands: awarded (publication → award), open (publication → deadline,
// with the days left), or otherwise its status over the same span.
function Period({ t }) {
  const deadline = typeof t.deadline === 'string' ? t.deadline : t.deadline?.date
  const award = (t.lots || []).map((l) => l.result?.date).filter(Boolean).sort()[0]
  const days = deadline ? Math.ceil((new Date(`${deadline}T23:59:59`) - new Date()) / 86400000) : NaN
  const open = !award && days >= 0
  const st = tenderState(t)
  const label = award ? 'Adjudicada' : open ? 'Abierta' : st?.es
  const cls = award ? 'st-done' : open ? 'st-open' : st?.cls
  const end = award || deadline
  if (!label && !t.published && !end) return null
  const left = !open ? null : days === 0 ? 'hoy' : days === 1 ? 'mañana' : `en ${days} días`
  return (
    <div className="tv-period">
      {label && <span className={`status ${cls}`} title={t.status || undefined}>{label}</span>}
      <span className="tv-range">
        {t.published ? <Tip tip="Publicación del primer anuncio en la Plataforma de Contratación">{dmy(t.published)}</Tip> : '…'}
        {' '}<span className="muted">→</span>{' '}
        {end ? <Tip tip={award ? 'Fecha de adjudicación' : 'Fin del plazo de presentación de ofertas'}>{dmy(end)}</Tip> : '…'}
      </span>
      {left && <span className="dl-open">({left})</span>}
    </div>
  )
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
function fmtDuration(d) {
  if (typeof d !== 'object') return String(d)
  const n = d.amount ?? d.value
  const unit = (n === 1 ? UNIT1 : UNIT)[d.unit] || d.unit_label || d.unit
  const span = [d.start, d.end].filter(Boolean).map(dmy).join(' → ')
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
        <nav className="seg" aria-label="Lotes">
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
          {(l.value != null || l.budget != null) && <div><dt>Importe</dt><dd><Money value={l.value} budget={l.budget} /></dd></div>}
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
              <li key={k}>{b.winner && <Trophy size={14} className="ico ico-win" aria-label="Adjudicataria" />}{b.bidders.map((o) => (
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
const CRIT_GROUP = { JUDGEMENT: 'Evaluables mediante juicio de valor', FORMULA: 'Evaluables mediante fórmulas', OTHER: 'Sin tipo' }
const CRIT_ORDER = ['JUDGEMENT', 'FORMULA', 'OTHER']
const CRIT_COLOR = { JUDGEMENT: '#b4637a', FORMULA: '#6d5bd0' }
const kindOf = (c) => (CRIT_KIND[c.subtype] ? c.subtype : 'OTHER')

// Criteria grouped by how they are scored (judgement, then formulas), each with its weight in the
// lot's total; the bar and the rows light each other up on hover. A criterion's name shows where
// it was found on hover; its formula (from the pipeline, or found in its text) opens below it.
// The calculator holds the values of every formula (the same ones an opened formula shows) and
// an estimate for each judged one.
function Criteria({ lot }) {
  const cs = useMemo(() => [...(lot.award_criteria || [])]
    .sort((x, y) => CRIT_ORDER.indexOf(kindOf(x)) - CRIT_ORDER.indexOf(kindOf(y))), [lot])
  const [open, setOpen] = useState(null)
  const [hot, setHot] = useState(null)
  const [calc, setCalc] = useState(false)
  const models = useMemo(() => cs.map((c) => {
    const model = c.formula_model || guessModel([c.detail?.formula, c.formula].filter(Boolean).join('\n'))
    const parsed = model && parseModel(model)
    return model && !parsed.error ? { model, parsed } : model ? { model } : null
  }), [cs])
  const [vals, setVals] = useState({})
  const valuesOf = (k) => vals[k] || (models[k]?.parsed ? startValues(models[k].model, models[k].parsed, cs[k].points) : {})
  const setValuesOf = (k) => (v) => setVals((x) => ({ ...x, [k]: v }))
  if (!cs.length) return null
  const total = cs.reduce((n, c) => n + (c.points || 0), 0)
  const pct = (p) => (total ? (100 * (p || 0)) / total : 0)
  const groups = CRIT_ORDER.map((kind) => ({ kind, items: cs.map((c, k) => ({ c, k })).filter(({ c }) => kindOf(c) === kind) }))
    .filter((g) => g.items.length)
  const color = (c) => CRIT_COLOR[c.subtype] || '#94a3b8'
  return (
    <section className="tv-card">
      <div className="cr-head">
        <h3>Criterios de adjudicación <span className="muted">· {fmtNum(total)} puntos</span></h3>
        <button type="button" className="linkish small" onClick={() => setCalc(!calc)}>{calc ? 'Cerrar calculadora' : 'Calcular una puntuación'}</button>
      </div>
      {calc && <Calculator cs={cs} models={models} valuesOf={valuesOf} setValuesOf={setValuesOf} total={total} />}
      {total > 0 && (
        <div className={`cr-bar ${hot != null ? 'has-hot' : ''}`} role="img" aria-label="Peso de cada criterio" onMouseLeave={() => setHot(null)}>
          {cs.map((c, k) => c.points ? (
            <span key={k} className={hot === k ? 'hot' : ''} onMouseEnter={() => setHot(k)}
              style={{ width: `${pct(c.points)}%`, background: color(c) }}
              title={`${c.name}: ${fmtNum(c.points)} puntos (${fmtNum(pct(c.points))} %)`} />
          ) : null)}
        </div>
      )}
      <table className="ptable cr-table">
        <thead><tr><th>Criterio</th><th className="num">Puntos</th><th>Peso</th><th /></tr></thead>
        {groups.map((g) => {
          const pts = g.items.reduce((n, { c }) => n + (c.points || 0), 0)
          return (
            <tbody key={g.kind}>
              <tr className="cr-group"><td colSpan={4}>
                <i style={{ background: CRIT_COLOR[g.kind] || '#94a3b8' }} />{CRIT_GROUP[g.kind]}
                <span className="muted"> · {fmtNum(pts)} puntos{total ? ` (${fmtNum(pct(pts))} %)` : ''}</span>
              </td></tr>
              {g.items.map(({ c, k }) => {
                const model = models[k]?.model
                const isOpen = open === k
                const name = (
                  <div className="cr-cell">
                    <span className="cr-name">{c.name}</span>
                    {c.description && <span className="cr-desc">{c.description}</span>}
                    {c.formula && !c.formula_model && <span className="cr-raw">{c.formula}</span>}
                    {c.conflicts && <span className="small warn-text">Discrepancia: {Object.entries(c.conflicts).map(([key, vs]) => `${key} ${vs.map((v) => v.value).join(' / ')}`).join('; ')}</span>}
                  </div>
                )
                return (
                  <Fragment key={k}>
                    <tr className={`cr-row ${hot === k ? 'hot' : ''}`} style={{ '--cr': color(c) }} onMouseEnter={() => setHot(k)} onMouseLeave={() => setHot(null)}>
                      <td>{c.id ? <SourceHover id={c.id} block>{name}</SourceHover> : name}</td>
                      <td className="num cr-pts">{c.points != null ? fmtNum(c.points) : '—'}</td>
                      <td className="cr-w">{c.points ? <><span className="cr-wbar"><i style={{ width: `${pct(c.points)}%`, background: color(c) }} /></span> {fmtNum(pct(c.points))} %</> : null}</td>
                      <td>{model && <button type="button" className="linkish small" onClick={() => setOpen(isOpen ? null : k)}>{isOpen ? 'Ocultar' : 'Ver fórmula'}</button>}</td>
                    </tr>
                    {isOpen && model && <tr className="cr-fx"><td colSpan={4}><FormulaView model={model} points={c.points} values={models[k]?.parsed ? valuesOf(k) : undefined} onValues={setValuesOf(k)} /></td></tr>}
                  </Fragment>
                )
              })}
            </tbody>
          )
        })}
      </table>
    </section>
  )
}

// One row per criterion: the symbols of its formula that the text leaves open (what the bidder
// offers, the other offers), or for a judged one the points expected; its score capped to
// [0, points]; the total at the foot.
function Calculator({ cs, models, valuesOf, setValuesOf, total }) {
  let sum = 0, missing = 0
  const rows = cs.map((c, k) => {
    const m = models[k]
    const vs = valuesOf(k)
    let score = null, open = []
    if (m?.parsed) {
      open = freeSymbols(m.model, m.parsed).filter((v) => v.kind !== 'constant' && v.kind !== 'output' && !(v.value != null && v.kind === 'parameter'))
      try { score = evaluate(m.parsed.ast, vs) } catch { score = null }
    } else score = vs.estimate ?? null
    if (score != null && Number.isFinite(score)) score = Math.max(0, c.points ? Math.min(c.points, score) : score)
    else score = null
    if (score == null) missing++
    else sum += score
    return { c, k, m, vs, score, open }
  })
  const set = (k, vs, sym) => (e) => setValuesOf(k)({ ...vs, [sym]: e.target.value === '' ? null : Number(e.target.value) })
  return (
    <div className="cr-calc">
      {rows.map(({ c, k, m, vs, score, open }) => (
        <div key={k} className="cr-calc-row">
          <div className="cr-calc-name">{c.name}</div>
          <div className="cr-calc-in">
            {m?.parsed ? open.map((v) => (
              <label key={v.symbol} title={v.meaning || v.symbol}>
                <Tex>{symbolTex(v.symbol)}</Tex>
                <span className="cr-calc-mean">{v.meaning || ''}{v.unit ? ` (${v.unit})` : ''}</span>
                <input type="number" step="any" className="fx-in" value={vs[v.symbol] ?? ''} min={v.min ?? undefined} max={v.max ?? undefined} onChange={set(k, vs, v.symbol)} />
              </label>
            )) : (
              <label><span className="cr-calc-mean muted">{c.subtype === 'JUDGEMENT' ? 'Puntos que esperas del comité' : 'Puntos estimados (sin fórmula leída)'}</span>
                <input type="number" step="any" className="fx-in" value={vs.estimate ?? ''} min={0} max={c.points ?? undefined} onChange={set(k, vs, 'estimate')} />
              </label>
            )}
          </div>
          <b className="cr-calc-score">{score != null ? fmtNum(score) : '—'}<span className="muted"> / {c.points != null ? fmtNum(c.points) : '—'}</span></b>
        </div>
      ))}
      <div className="cr-calc-row cr-calc-total">
        <div className="cr-calc-name">Total{missing ? <span className="muted small"> · faltan {missing} {missing === 1 ? 'criterio' : 'criterios'}</span> : null}</div>
        <div />
        <b className="cr-calc-score">{fmtNum(sum)}<span className="muted"> / {fmtNum(total)}</span></b>
      </div>
    </div>
  )
}

const fmtNum = (x) => Number(x || 0).toLocaleString('es-ES', { maximumFractionDigits: 1 })

// Requirement types, in the order they are listed: the refinement's (entities.py REFINE_SCHEMAS)
// and the feed's (graph.py _feed_req_kind), which share a heading where they mean the same.
const REQ_TYPE = [
  ['CLASSIFICATION', 'Clasificación empresarial'],
  ['ECONOMIC_TURNOVER', 'Volumen anual de negocios'], ['TURNOVER', 'Volumen anual de negocios'],
  ['ECONOMIC_NET_WORTH', 'Patrimonio neto y ratios financieros'],
  ['INSURANCE', 'Seguro de responsabilidad'],
  ['SIMILAR_WORK', 'Trabajos similares ejecutados'], ['SIMILAR_SERVICES', 'Trabajos similares ejecutados'],
  ['STAFF_QUALIFICATION', 'Titulación y experiencia del personal'], ['TEAM', 'Titulación y experiencia del personal'],
  ['TEAM_MINIMUM', 'Equipo mínimo'],
  ['MATERIAL_MEANS', 'Medios materiales'],
  ['CERTIFICATION', 'Certificaciones y normas'], ['CREDENTIAL', 'Certificaciones y normas'],
  ['PROFESSIONAL_REGISTRATION', 'Habilitación profesional'],
  ['TECHNICAL_SPECIFICATION', 'Especificaciones técnicas'],
  ['COMMITMENT', 'Compromisos de adscripción de medios'],
]
const REQ_ES = Object.fromEntries(REQ_TYPE)
const REQ_RANK = Object.fromEntries([...new Set(REQ_TYPE.map(([, es]) => es))].map((es, i) => [es, i]))
const reqType = (r) => REQ_ES[r.detail?.subtype || r.subtype] || (r.label && !['Requirement', 'TechnicalRequirement'].includes(r.label) ? nodeInfo(r.label).es : 'Otros')

function Requirements({ reqs, title }) {
  if (!reqs.length) return null
  // Requirements a feed line points to ("según cláusula 8ª") are listed under that line.
  const byId = Object.fromEntries(reqs.map((r) => [r.id, r]))
  const nested = new Set(reqs.flatMap((r) => r.detailed_by || []))
  const item = (r, child = false) => (
    <li key={r.id || r.name} className={child ? 'req-child' : ''}>
      {r.id ? <SourceHover id={r.id}><span className="req-name">{r.name || r.text}</span></SourceHover>
        : <span className="req-name">{r.name || r.text}</span>}
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
  const groups = {}
  for (const r of reqs.filter((x) => !nested.has(x.id))) (groups[reqType(r)] ||= []).push(r)
  const order = Object.keys(groups).sort((x, y) => (REQ_RANK[x] ?? 98) - (REQ_RANK[y] ?? 98) || (x === 'Otros') - (y === 'Otros'))
  return (
    <>
      <h4>{title}</h4>
      {order.map((type) => (
        <div key={type} className="req-group">
          <div className="req-type">{type} <span className="muted">· {groups[type].length}</span></div>
          <ul className="plain">{groups[type].map((r) => item(r))}</ul>
        </div>
      ))}
    </>
  )
}

// A document is one card: anywhere on it opens its text; the one link out is to the original where
// it was published.
function Documents({ t }) {
  const docs = t.documents || []
  const read = (d) => go(`/t/${t.tender_id}/d/${d.sha256}`)
  return (
    <ol className="docs">
      {docs.map((d) => (
        <li key={d.sha256} className="tv-card doc is-link" tabIndex={0}
          onClick={(e) => { if (!e.target.closest('a, button')) read(d) }}
          onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) read(d) }}>
          <div className="doc-seq">{d.seq}</div>
          <div className="doc-main">
            <div className="doc-meta">
              <span className="chip">{roleEs(d.role)}</span>
              <Tip tip={docDateTip(d)}><time>{dmy(d.effective_date) || 'sin fecha'}</time></Tip>
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
              <ExtLink href={d.url}>Original</ExtLink>
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
