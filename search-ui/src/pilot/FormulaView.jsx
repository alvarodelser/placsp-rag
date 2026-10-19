// search-ui/src/pilot/FormulaView.jsx — a criterion's scoring formula, compact: on the left the
// formula and its symbols (what each one is, its value to try); on the right the score as a curve
// of the symbol picked as x axis, the current value marked. Click a symbol to make it the axis.
import { useMemo, useState } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { parse, evaluate, toLatex, symbolTex, defaultRange, niceTicks } from './formula.js'

export function Tex({ children, display = false }) {
  const html = useMemo(() => {
    try { return katex.renderToString(children, { displayMode: display, throwOnError: false, output: 'html' }) }
    catch { return children }
  }, [children, display])
  return <span className={display ? 'tex-block' : 'tex'} dangerouslySetInnerHTML={{ __html: html }} />
}

export default function FormulaView({ model, points }) {
  const parsed = useMemo(() => { try { return parse(model.expression) } catch (e) { return { error: e.message } } }, [model])
  if (parsed.error) {
    return <div className="fx"><div className="small warn-text">No se pudo leer la fórmula ({parsed.error}).</div>
      {model.source_text && <blockquote className="fx-src">{model.source_text}</blockquote>}</div>
  }
  return <Formula model={model} parsed={parsed} points={points} />
}

function Formula({ model, parsed, points }) {
  const free = useMemo(() => {
    const declared = Object.fromEntries((model.variables || []).map((v) => [v.symbol, v]))
    return parsed.symbols.map((s) => declared[s] || { symbol: s, kind: 'input', meaning: null, value: null })
  }, [model, parsed])
  const out = (model.variables || []).find((v) => v.symbol === parsed.out)
  const [values, setValues] = useState(() => Object.fromEntries(free.map((v) => [v.symbol, start(v, points)])))
  const [axis, setAxis] = useState(() => (free.find((v) => v.kind === 'input') || free[0])?.symbol)

  let score = null
  try { score = evaluate(parsed.ast, values) } catch { score = null }

  return (
    <div className="fx2">
      <div className="fx2-left">
        <div className="fx-math"><Tex display>{toLatex(parsed)}</Tex></div>
        <ul className="fx2-syms">
          <li className="fx2-out">
            <Tex>{symbolTex(parsed.out)}</Tex>
            <span className="fx2-mean">{out?.meaning || 'Puntuación'}</span>
            <b className="fx2-val">{fmt(score)}{points ? <span className="muted"> / {fmt(points)}</span> : null}</b>
          </li>
          {free.map((v) => (
            <li key={v.symbol} className={axis === v.symbol ? 'on' : ''} onClick={() => setAxis(v.symbol)} title="Clic: ver la puntuación según este símbolo">
              <Tex>{symbolTex(v.symbol)}</Tex>
              <span className="fx2-mean">{v.meaning || <span className="muted">—</span>}{v.unit ? <span className="muted"> ({v.unit})</span> : null}</span>
              <input type="number" step="any" className="fx-in" value={values[v.symbol] ?? ''} onClick={(e) => e.stopPropagation()}
                onChange={(e) => setValues((x) => ({ ...x, [v.symbol]: e.target.value === '' ? null : Number(e.target.value) }))} />
            </li>
          ))}
        </ul>
        <div className="fx2-notes small">
          <span className={`chip ${model.literal ? '' : 'fx-deduced'}`}>{model.guessed ? 'Detectada en el texto del criterio' : model.literal ? 'Fórmula del pliego' : 'Deducida de una regla en palabras'}</span>
          {model.guessed && <span className="muted"> Los símbolos se explicarán cuando el pipeline procese este criterio.</span>}
          {points && score > points + 1e-9 && <span className="warn-text"> Supera el máximo: el pliego la limita.</span>}
          {(model.conditions || []).length > 0 && <ul className="plain">{model.conditions.map((c, i) => <li key={i}>• {c}</li>)}</ul>}
          {model.source_text && <details><summary>Texto del pliego</summary><blockquote className="fx-src">{model.source_text}</blockquote></details>}
        </div>
      </div>
      <div className="fx2-right">
        {axis ? <Plot parsed={parsed} axis={free.find((v) => v.symbol === axis)} values={values} points={points} out={parsed.out} />
          : <div className="muted small">Sin símbolos que variar.</div>}
      </div>
    </div>
  )
}

function start(v, points) {
  if (v.value != null) return v.value
  if (v.kind === 'constant' && /punt/i.test(`${v.unit} ${v.meaning}`) && points) return points
  return 100
}

const fmt = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toLocaleString('es-ES', { maximumFractionDigits: 2 }))
const fmtTick = (t) => t.toLocaleString('es-ES', { maximumFractionDigits: 2 })
const PW = 420, PH = 240, M = { l: 40, r: 12, t: 12, b: 34 }

// The score against one symbol, the others held at their values. The range is set when the axis
// is chosen (around its value then), so typing a value moves the dot, not the axes.
function Plot({ parsed, axis, values, points, out }) {
  const [a, b] = useMemo(() => defaultRange(values[axis.symbol], axis.unit), [axis.symbol]) // eslint-disable-line react-hooks/exhaustive-deps
  const { pts, y0, y1 } = useMemo(() => {
    const pts = []
    for (let i = 0; i <= 160; i++) {
      const x = a + (b - a) * i / 160
      let y = null
      try { y = evaluate(parsed.ast, { ...values, [axis.symbol]: x }) } catch { y = null }
      pts.push([x, Number.isFinite(y) ? y : null])
    }
    const ys = pts.map((p) => p[1]).filter((y) => y != null)
    let y0 = Math.min(0, ...ys), y1 = Math.max(points || 0, ...ys)
    if (points && y1 > points * 4) y1 = points * 1.5
    if (y1 - y0 < 1e-9) y1 = y0 + 1
    return { pts, y0, y1 }
  }, [parsed, values, axis.symbol, a, b, points])
  const sx = (x) => M.l + (x - a) / (b - a || 1) * (PW - M.l - M.r)
  const sy = (y) => PH - M.b - (Math.max(y0, Math.min(y1, y)) - y0) / (y1 - y0) * (PH - M.t - M.b)
  const paths = []
  let cur = []
  for (const [x, y] of pts) {
    if (y == null || y > y1 * 1.5 || y < y0 - (y1 - y0)) { if (cur.length) paths.push(cur); cur = []; continue }
    cur.push(`${sx(x).toFixed(1)},${sy(y).toFixed(1)}`)
  }
  if (cur.length) paths.push(cur)
  let dot = null
  try { const y = evaluate(parsed.ast, values); if (Number.isFinite(y) && values[axis.symbol] >= a && values[axis.symbol] <= b) dot = [values[axis.symbol], y] } catch { dot = null }

  return (
    <svg viewBox={`0 0 ${PW} ${PH}`} className="fx-svg" role="img" aria-label={`Puntuación ${out} según ${axis.symbol}`}>
      {niceTicks(y0, y1, 4).map((t) => <g key={`y${t}`}><line x1={M.l} x2={PW - M.r} y1={sy(t)} y2={sy(t)} className="fx-grid" />
        <text x={M.l - 5} y={sy(t) + 3.5} textAnchor="end" className="fx-tick">{fmtTick(t)}</text></g>)}
      {niceTicks(a, b, 4).map((t) => <text key={`x${t}`} x={sx(t)} y={PH - M.b + 14} textAnchor="middle" className="fx-tick">{fmtTick(t)}</text>)}
      <line x1={M.l} x2={PW - M.r} y1={PH - M.b} y2={PH - M.b} className="fx-axis" />
      <line x1={M.l} x2={M.l} y1={M.t} y2={PH - M.b} className="fx-axis" />
      {points ? <line x1={M.l} x2={PW - M.r} y1={sy(points)} y2={sy(points)} className="fx-max" /> : null}
      {paths.map((p, i) => <polyline key={i} points={p.join(' ')} className="fx-line" />)}
      {dot && <circle cx={sx(dot[0])} cy={sy(dot[1])} r={4.5} className="fx-dot"><title>{`${axis.symbol} = ${fmt(dot[0])} → ${out} = ${fmt(dot[1])}`}</title></circle>}
      <text x={(M.l + PW - M.r) / 2} y={PH - 4} textAnchor="middle" className="fx-label">{axis.symbol}{axis.meaning ? ` · ${axis.meaning}` : ''}</text>
    </svg>
  )
}
