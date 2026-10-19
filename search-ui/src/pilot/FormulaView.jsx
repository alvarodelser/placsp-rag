// search-ui/src/pilot/FormulaView.jsx — a criterion's scoring formula: written as mathematics, every
// symbol explained, and a small calculator: give each symbol a value and read the score, or pick
// one symbol as the x axis and see the score as a curve with the current offer marked on it.
import { useMemo, useState } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { parse, evaluate, toLatex, symbolTex, defaultRange, niceTicks } from './formula.js'

const KIND = { output: 'Puntuación', input: 'Oferta del licitador', parameter: 'Dato del expediente', constant: 'Constante' }

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
    return (
      <div className="fx">
        <div className="small warn-text">No se pudo leer la fórmula ({parsed.error}).</div>
        {model.source_text && <blockquote className="fx-src">{model.source_text}</blockquote>}
      </div>
    )
  }
  return <Formula model={model} parsed={parsed} points={points} />
}

function Formula({ model, parsed, points }) {
  const vars = useMemo(() => {
    const declared = Object.fromEntries((model.variables || []).map((v) => [v.symbol, v]))
    // Every symbol on the right gets a row, declared or not; the output first.
    return [declared[parsed.out] || { symbol: parsed.out, kind: 'output', meaning: 'Puntuación' },
      ...parsed.symbols.map((s) => declared[s] || { symbol: s, kind: 'input', meaning: 'sin explicar en el texto', value: null })]
  }, [model, parsed])
  const free = vars.filter((v) => v.kind !== 'output')
  const [values, setValues] = useState(() => Object.fromEntries(free.map((v) => [v.symbol, start(v, points)])))
  const [axis, setAxis] = useState(() => (free.find((v) => v.kind === 'input') || free[0])?.symbol)

  let score = null, error = null
  try { score = evaluate(parsed.ast, values) } catch (e) { error = e.message }

  return (
    <div className="fx">
      <div className="fx-head">
        <span className={`chip ${model.literal ? '' : 'fx-deduced'}`}>{model.literal ? 'Fórmula del pliego' : 'Deducida de una regla escrita en palabras'}</span>
      </div>
      <div className="fx-math"><Tex display>{toLatex(parsed)}</Tex></div>
      <table className="ptable fx-vars">
        <thead><tr><th>Símbolo</th><th>Qué es</th><th>Tipo</th><th className="num">Valor</th></tr></thead>
        <tbody>
          {vars.map((v) => (
            <tr key={v.symbol}>
              <td><Tex>{symbolTex(v.symbol)}</Tex></td>
              <td>{v.meaning}{v.unit ? <span className="muted"> ({v.unit})</span> : null}</td>
              <td className="muted small">{KIND[v.kind] || v.kind}</td>
              <td className="num">
                {v.kind === 'output' ? <b>{error ? '—' : fmt(score)}</b> : (
                  <input type="number" className="fx-in" value={values[v.symbol] ?? ''} step="any"
                    onChange={(e) => setValues((x) => ({ ...x, [v.symbol]: e.target.value === '' ? null : Number(e.target.value) }))} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="fx-score">
        {error ? <span className="muted">{error}</span> : (
          <>Puntuación: <b>{fmt(score)}</b>{points ? <span className="muted"> de {fmt(points)} puntos</span> : null}
            {points && score > points + 1e-9 ? <span className="warn-text"> · supera el máximo: el pliego la limita</span> : null}
            {score < 0 ? <span className="warn-text"> · negativa: el pliego suele dar 0</span> : null}</>
        )}
      </div>
      {free.length > 0 && <Plot parsed={parsed} vars={free} values={values} axis={axis} setAxis={setAxis} points={points} out={parsed.out}
        onValue={(sym, x) => setValues((s) => ({ ...s, [sym]: x }))} />}
      {(model.conditions || []).length > 0 && (
        <div className="fx-cond"><div className="np-rel">Reglas que la fórmula no recoge</div>
          <ul className="plain small">{model.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
      )}
      {model.source_text && <details className="small"><summary>Texto del pliego</summary><blockquote className="fx-src">{model.source_text}</blockquote></details>}
    </div>
  )
}

function start(v, points) {
  if (v.value != null) return v.value
  if (v.kind === 'constant' && /punt/i.test(`${v.unit} ${v.meaning}`) && points) return points
  return 100
}

const fmt = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toLocaleString('es-ES', { maximumFractionDigits: 3 }))

const PW = 560, PH = 260, M = { l: 48, r: 16, t: 14, b: 40 }

function Plot({ parsed, vars, values, axis, setAxis, points, out, onValue }) {
  const v = vars.find((x) => x.symbol === axis) || vars[0]
  const [range, setRange] = useState({})
  const [a, b] = range[v.symbol] || defaultRange(values[v.symbol], v.unit)

  const { pts, y0, y1 } = useMemo(() => {
    const pts = []
    for (let i = 0; i <= 200; i++) {
      const x = a + (b - a) * i / 200
      let y = null
      try { y = evaluate(parsed.ast, { ...values, [v.symbol]: x }) } catch { y = null }
      pts.push([x, Number.isFinite(y) ? y : null])
    }
    const ys = pts.map((p) => p[1]).filter((y) => y != null)
    let y0 = Math.min(0, ...ys), y1 = Math.max(points || 0, ...ys)
    if (y1 - y0 < 1e-9) y1 = y0 + 1
    // A curve that runs off to infinity (a division by zero) keeps the axis at a readable height.
    if (points && y1 > points * 4) y1 = points * 1.5
    return { pts, y0, y1 }
  }, [parsed, values, v.symbol, a, b, points])

  const sx = (x) => M.l + (x - a) / (b - a || 1) * (PW - M.l - M.r)
  const sy = (y) => PH - M.b - (Math.max(y0, Math.min(y1, y)) - y0) / (y1 - y0) * (PH - M.t - M.b)
  const paths = []
  let cur = []
  for (const [x, y] of pts) {
    if (y == null || y > y1 * 1.5 || y < y0 - (y1 - y0)) { if (cur.length) paths.push(cur); cur = []; continue }
    cur.push(`${sx(x).toFixed(1)},${sy(y).toFixed(1)}`)
  }
  if (cur.length) paths.push(cur)
  let here = null
  try { here = [values[v.symbol], evaluate(parsed.ast, values)] } catch { here = null }

  return (
    <div className="fx-plot">
      <div className="fx-plot-bar">
        <label>Eje x
          <select value={v.symbol} onChange={(e) => setAxis(e.target.value)}>
            {vars.map((x) => <option key={x.symbol} value={x.symbol}>{x.symbol} · {x.meaning}</option>)}
          </select>
        </label>
        <label>de <input type="number" className="fx-in" value={a} step="any" onChange={(e) => setRange((r) => ({ ...r, [v.symbol]: [Number(e.target.value), b] }))} /></label>
        <label>a <input type="number" className="fx-in" value={b} step="any" onChange={(e) => setRange((r) => ({ ...r, [v.symbol]: [a, Number(e.target.value)] }))} /></label>
        <input type="range" min={a} max={b} step={(b - a) / 200 || 1} value={values[v.symbol] ?? a} aria-label={`Valor de ${v.symbol}`}
          onChange={(e) => onValue(v.symbol, Number(e.target.value))} className="fx-slider" />
      </div>
      <svg viewBox={`0 0 ${PW} ${PH}`} className="fx-svg" role="img" aria-label={`Puntuación ${out} según ${v.symbol}`}>
        {niceTicks(y0, y1).map((t) => (
          <g key={`y${t}`}><line x1={M.l} x2={PW - M.r} y1={sy(t)} y2={sy(t)} className="fx-grid" />
            <text x={M.l - 6} y={sy(t) + 4} textAnchor="end" className="fx-tick">{fmtTick(t)}</text></g>
        ))}
        {niceTicks(a, b).map((t) => (
          <g key={`x${t}`}><line x1={sx(t)} x2={sx(t)} y1={M.t} y2={PH - M.b} className="fx-grid" />
            <text x={sx(t)} y={PH - M.b + 15} textAnchor="middle" className="fx-tick">{fmtTick(t)}</text></g>
        ))}
        <line x1={M.l} x2={PW - M.r} y1={PH - M.b} y2={PH - M.b} className="fx-axis" />
        <line x1={M.l} x2={M.l} y1={M.t} y2={PH - M.b} className="fx-axis" />
        {points ? <><line x1={M.l} x2={PW - M.r} y1={sy(points)} y2={sy(points)} className="fx-max" />
          <text x={PW - M.r} y={sy(points) - 4} textAnchor="end" className="fx-tick">máximo {fmtTick(points)}</text></> : null}
        {paths.map((p, i) => <polyline key={i} points={p.join(' ')} className="fx-line" />)}
        {here && Number.isFinite(here[1]) && here[0] >= a && here[0] <= b && (
          <circle cx={sx(here[0])} cy={sy(here[1])} r={4.5} className="fx-dot"><title>{`${v.symbol} = ${fmt(here[0])} → ${out} = ${fmt(here[1])}`}</title></circle>
        )}
        <text x={(M.l + PW - M.r) / 2} y={PH - 6} textAnchor="middle" className="fx-label">{v.symbol} · {v.meaning}</text>
        <text x={12} y={(M.t + PH - M.b) / 2} textAnchor="middle" className="fx-label" transform={`rotate(-90 12 ${(M.t + PH - M.b) / 2})`}>{out}</text>
      </svg>
    </div>
  )
}

const fmtTick = (t) => t.toLocaleString('es-ES', { maximumFractionDigits: 2 })
