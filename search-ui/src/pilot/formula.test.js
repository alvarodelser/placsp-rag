import { describe, expect, it } from 'vitest'
import { parse, evaluate, toLatex, niceTicks } from './formula.js'

describe('formula', () => {
  it('parses and evaluates a proportional price formula', () => {
    const f = parse('P = Pmax * (PL - Of) / (PL - Of_min)')
    expect(f.out).toBe('P')
    expect(f.symbols.sort()).toEqual(['Of', 'Of_min', 'PL', 'Pmax'])
    expect(evaluate(f.ast, { Pmax: 80, PL: 100, Of: 90, Of_min: 80 })).toBeCloseTo(40)
  })

  it('reads tiers as nested ifs and powers right to left', () => {
    const f = parse('P = if(A >= 3, 20, if(A >= 2, 7, if(A >= 1, 4, 0)))')
    expect([0, 1, 2, 5].map((A) => evaluate(f.ast, { A }))).toEqual([0, 4, 7, 20])
    expect(evaluate(parse('y = 2 ^ 3 ^ 2').ast, {})).toBe(512)
    expect(evaluate(parse('y = -x ^ 2 + min(1, 2, x)').ast, { x: 3 })).toBe(-8)
  })

  it('writes LaTeX with fractions, subscripts and cases', () => {
    expect(toLatex(parse('P = Pmax * Of_min / Of'))).toBe('P = \\dfrac{\\mathit{Pmax} \\cdot \\mathit{Of}_{\\mathit{min}}}{\\mathit{Of}}')
    expect(toLatex(parse('P = if(A >= 3, 20, 0)'))).toContain('\\begin{cases} 20 & \\text{si } A \\ge 3')
    expect(toLatex(parse('P = (a + b) * c'))).toBe('P = \\left(a + b\\right) \\cdot c')
  })

  it('rejects what is not the language', () => {
    expect(() => parse('80 * Bi')).toThrow()
    expect(() => parse('P = alert(1)')).toThrow(/desconocida/)
    expect(() => parse('P = 3 +')).toThrow()
    expect(() => parse('P = a; b')).toThrow()
    expect(() => evaluate(parse('P = a + 1').ast, {})).toThrow(/a/)
  })

  it('reads quoted yes/no answers as 1 and 0', () => {
    const f = parse("P = if(Cert == 'SI', 4.0, 0)")
    expect(evaluate(f.ast, { Cert: 1 })).toBe(4)
    expect(evaluate(f.ast, { Cert: 0 })).toBe(0)
    expect(toLatex(f)).toContain('\\text{SI}')
    expect(() => parse("P = if(Tipo == 'grande', 4, 0)")).toThrow(/grande/)
  })

  it('ticks land on round numbers', () => {
    expect(niceTicks(0, 100)).toEqual([0, 20, 40, 60, 80, 100])
    expect(niceTicks(0, 1)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1])
  })
})

describe('guessModel', () => {
  it('finds a formula in prose', async () => {
    const { guessModel } = await import('./formula.js')
    expect(guessModel('La puntuación se obtiene así: P = 30 x (Ofmin / Of) siendo Of la oferta.').expression).toBe('P = 30 * (Ofmin / Of)')
    expect(guessModel('Pi = Pmax × (PL − Oi) / (PL − Omin)').expression).toBe('Pi = Pmax * (PL - Oi) / (PL - Omin)')
    expect(guessModel('Se valorará la rebaja del precio de licitación propuesto.')).toBeNull()
  })
})

describe('ranges and tiers', () => {
  it('takes the range from the model, else from the tier edges', async () => {
    const { rangeOf } = await import('./formula.js')
    const f = parse('P = if(A >= 3, 20, if(A >= 1, 7, 0))')
    expect(rangeOf({ symbol: 'A', min: 0, max: 5 }, f.ast)).toEqual([0, 5])
    expect(rangeOf({ symbol: 'A' }, f.ast)).toEqual([0, 4.5])
    expect(rangeOf({ symbol: 'X', unit: '%' }, f.ast)).toEqual([0, 100])
  })

  it('reads a step function of one symbol as tiers, and nothing else', async () => {
    const { stepTiers } = await import('./formula.js')
    expect(stepTiers(parse('P = if(A < 1, 0, 7)'))).toEqual({ symbol: 'A', rows: [{ op: '<', threshold: 1, value: 0 }], otherwise: 7 })
    expect(stepTiers(parse('P = if(1 > A, 0, Pmax)'), { Pmax: 7 }).rows[0]).toEqual({ op: '<', threshold: 1, value: 0 })
    expect(stepTiers(parse('P = if(A >= 3, 20 * A, 0)'))).toBeNull()
    expect(stepTiers(parse('P = if(A >= 3, 20, if(B >= 1, 7, 0))'))).toBeNull()
    expect(stepTiers(parse('P = Pmax * Of_min / Of'))).toBeNull()
  })
})
