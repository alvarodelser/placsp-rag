// search-ui/src/pilot/formula.js — the scoring formulas of award criteria: parse the expression the
// pipeline extracted (nlp_service criterion_formula), evaluate it and write it as LaTeX.
//
// Language (same as nlp/summarizer/formula.py): `OUT = expr` with numbers, symbols
// [A-Za-z][A-Za-z0-9_]*, + - * / ^ ( ), comparisons, if(c, a, b), min, max, abs, sqrt, ln, log10,
// exp, floor, ceil. A parse error throws; nothing is ever passed to eval().

const FUNCS = {
  min: Math.min, max: Math.max, abs: Math.abs, sqrt: Math.sqrt, ln: Math.log, log10: Math.log10,
  exp: Math.exp, floor: Math.floor, ceil: Math.ceil,
}
const BIN = { '+': [10, 'L'], '-': [10, 'L'], '*': [20, 'L'], '/': [20, 'L'], '^': [30, 'R'],
  '<': [5, 'L'], '<=': [5, 'L'], '>': [5, 'L'], '>=': [5, 'L'], '==': [5, 'L'], '!=': [5, 'L'] }

function tokens(s) {
  const out = []
  const re = /\s*(?:(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|([A-Za-z][A-Za-z0-9_]*)|(<=|>=|==|!=|[-+*/^(),<>]))/y
  let m
  re.lastIndex = 0
  while (re.lastIndex < s.length) {
    if (/^\s*$/.test(s.slice(re.lastIndex))) break
    const at = re.lastIndex
    if (!(m = re.exec(s))) throw new Error(`no se entiende «${s.slice(at, at + 12)}»`)
    out.push(m[1] ? { t: 'num', v: Number(m[1]) } : m[2] ? { t: 'id', v: m[2] } : { t: 'op', v: m[3] })
  }
  return out
}

// Pratt parser over the token list: AST nodes are {num}, {sym}, {neg}, {bin, op}, {call, f, args}.
export function parse(expression) {
  const eq = expression.search(/[^<>=!]=[^=]/)
  if (eq < 0) throw new Error('falta «SALIDA = expresión»')
  const out = expression.slice(0, eq + 1).trim()
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(out)) throw new Error('la izquierda debe ser un símbolo')
  const ts = tokens(expression.slice(eq + 2))
  let i = 0
  const peek = () => ts[i], next = () => ts[i++]
  const expect = (v) => { const t = next(); if (!t || t.v !== v) throw new Error(`se esperaba «${v}»`) }
  function primary() {
    const t = next()
    if (!t) throw new Error('expresión incompleta')
    if (t.t === 'num') return { num: t.v }
    if (t.v === '(') { const e = expr(0); expect(')'); return e }
    if (t.v === '-') return { neg: expr(25) }
    if (t.v === '+') return expr(25)
    if (t.t === 'id') {
      if (peek()?.v === '(') {
        next()
        const args = []
        if (peek()?.v !== ')') { do args.push(expr(0)); while (peek()?.v === ',' && next()) }
        expect(')')
        if (t.v !== 'if' && !FUNCS[t.v]) throw new Error(`función desconocida «${t.v}»`)
        if (t.v === 'if' && args.length !== 3) throw new Error('if necesita 3 argumentos')
        return { call: t.v, args }
      }
      return { sym: t.v }
    }
    throw new Error(`no se esperaba «${t.v}»`)
  }
  function expr(min) {
    let left = primary()
    for (;;) {
      const t = peek()
      const b = t && t.t === 'op' && BIN[t.v]
      if (!b || b[0] < min) return left
      next()
      left = { bin: t.v, l: left, r: expr(b[1] === 'L' ? b[0] + 1 : b[0]) }
    }
  }
  const ast = expr(0)
  if (i < ts.length) throw new Error(`sobra «${ts[i].v}»`)
  return { out, ast, symbols: [...collect(ast, new Set())] }
}

function collect(n, s) {
  if (n.sym) s.add(n.sym)
  for (const c of [n.neg, n.l, n.r, ...(n.args || [])]) if (c) collect(c, s)
  return s
}

export function evaluate(n, env) {
  if (n.num != null) return n.num
  if (n.sym) {
    const v = env[n.sym]
    if (v == null || Number.isNaN(v)) throw new Error(`falta el valor de ${n.sym}`)
    return v
  }
  if (n.neg) return -evaluate(n.neg, env)
  if (n.call === 'if') return evaluate(n.args[0], env) ? evaluate(n.args[1], env) : evaluate(n.args[2], env)
  if (n.call) return FUNCS[n.call](...n.args.map((a) => evaluate(a, env)))
  const l = evaluate(n.l, env), r = evaluate(n.r, env)
  switch (n.bin) {
    case '+': return l + r
    case '-': return l - r
    case '*': return l * r
    case '/': return l / r
    case '^': return l ** r
    case '<': return +(l < r)
    case '<=': return +(l <= r)
    case '>': return +(l > r)
    case '>=': return +(l >= r)
    case '==': return +(l === r)
    default: return +(l !== r)
  }
}

// ── LaTeX ─────────────────────────────────────────────────────────────────

const GREEK = new Set(['alpha', 'beta', 'gamma', 'delta', 'lambda', 'mu', 'sigma', 'theta', 'omega', 'pi'])

// Of_min → Of_{\min}-like subscript; Pmax stays one italic word; single letters stay italic.
export function symbolTex(s) {
  const [base, ...sub] = s.split('_')
  const b = GREEK.has(base.toLowerCase()) ? `\\${base}` : base.length > 1 ? `\\mathit{${base}}` : base
  return sub.length ? `${b}_{\\mathit{${sub.join(',')}}}` : b
}

const CMP = { '<': '<', '<=': '\\le', '>': '>', '>=': '\\ge', '==': '=', '!=': '\\ne' }
const PREC = (n) => (n.bin ? BIN[n.bin][0] : 100)

function tex(n, parent = 0) {
  if (n.num != null) return String(n.num).replace('.', '{,}')
  if (n.sym) return symbolTex(n.sym)
  if (n.neg) return `-${tex(n.neg, 25)}`
  if (n.call === 'if') return cases(n)
  if (n.call) {
    const args = n.args.map((a) => tex(a)).join(',\\ ')
    if (n.call === 'sqrt') return `\\sqrt{${args}}`
    if (n.call === 'abs') return `\\left|${args}\\right|`
    if (n.call === 'floor') return `\\lfloor ${args} \\rfloor`
    if (n.call === 'ceil') return `\\lceil ${args} \\rceil`
    const name = { min: '\\min', max: '\\max', ln: '\\ln', log10: '\\log_{10}', exp: '\\exp' }[n.call]
    return `${name}\\left(${args}\\right)`
  }
  let s
  if (n.bin === '/') s = `\\dfrac{${tex(n.l)}}{${tex(n.r)}}`
  else if (n.bin === '^') s = `{${tex(n.l, 31)}}^{${tex(n.r)}}`
  else if (n.bin === '*') s = `${tex(n.l, 20)} \\cdot ${tex(n.r, 21)}`
  else if (CMP[n.bin]) s = `${tex(n.l, 6)} ${CMP[n.bin]} ${tex(n.r, 6)}`
  else s = `${tex(n.l, 10)} ${n.bin} ${tex(n.r, n.bin === '-' ? 11 : 10)}`
  return PREC(n) < parent && n.bin !== '/' ? `\\left(${s}\\right)` : s
}

// Nested ifs read as tiers: one line per tier, the last one "en otro caso".
function cases(n) {
  const rows = []
  let x = n
  while (x.call === 'if') { rows.push(`${tex(x.args[1])} & \\text{si } ${tex(x.args[0])}`); x = x.args[2] }
  rows.push(`${tex(x)} & \\text{en otro caso}`)
  return `\\begin{cases} ${rows.join(' \\\\ ')} \\end{cases}`
}

export function toLatex(parsed) {
  return `${symbolTex(parsed.out)} = ${tex(parsed.ast)}`
}

// ── plotting help ─────────────────────────────────────────────────────────

// A range around a value that shows the shape: 0 to twice the value, or 0..100 without one.
export function defaultRange(v, unit) {
  if (unit === '%') return [0, 100]
  if (v == null || !Number.isFinite(v) || v === 0) return [0, 100]
  return v > 0 ? [0, v * 2] : [v * 2, 0]
}

export function niceTicks(a, b, n = 5) {
  const span = b - a || 1
  const step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0))
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0) || step0
  const out = []
  for (let v = Math.ceil(a / step) * step; v <= b + step * 1e-9; v += step) out.push(+v.toPrecision(12))
  return out
}

// ── a formula written in a criterion's text, before the pipeline has modelled it ─────────────

// "P = 30 x (Of_min / Of)", "Puntuación = Pmax × (PL − Oi) / (PL − Omin)": the first `SYMBOL = …`
// that parses, with ×, x, · as products, − as minus and decimal commas. Symbols are left
// unexplained: only the pipeline's model says what each one means.
export function guessModel(text) {
  if (!text) return null
  const norm = text.replace(/[−–]/g, '-').replace(/[×·∙]/g, '*').replace(/(\S)\s+[xX]\s+(\S)/g, '$1 * $2')
    .replace(/(\d),(\d)/g, '$1.$2').replace(/[\r\n]+/g, '\n')
  const re = /([A-Za-z][A-Za-z0-9_]*)\s*=\s*([^\n;:]+)/g
  let m
  while ((m = re.exec(norm))) {
    const words = m[2].trim().replace(/\.$/, '').split(/\s+/)
    for (let n = words.length; n > 0; n--) {          // drop trailing prose until it parses
      const expression = `${m[1]} = ${words.slice(0, n).join(' ')}`
      try {
        const p = parse(expression)
        if (!p.symbols.length) break
        return { has_formula: true, literal: true, guessed: true, expression, conditions: [], source_text: m[0].trim(),
          variables: [{ symbol: p.out, kind: 'output', meaning: 'Puntuación' }] }
      } catch { /* shorter */ }
    }
  }
  return null
}
