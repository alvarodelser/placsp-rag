import { describe, expect, it } from 'vitest'
import { claims, sources, excerpt } from './cites.js'

const P = (sha, page, text = '') => ({ doc_sha256: sha, page_from: page, text })

describe('cites', () => {
  it('splits an answer into claims back to the sentence start', () => {
    const parts = claims('Se exige un volumen de 450.000 € [1][2]. La garantía es del 5 % [F]. Nada más.', 2)
    expect(parts.filter((p) => p.refs).map((p) => [p.text, p.refs])).toEqual([
      ['Se exige un volumen de 450.000 €', [1, 2]], ['La garantía es del 5 %', ['F']]])
    expect(parts.map((p) => p.text).join('')).toBe('Se exige un volumen de 450.000 €. La garantía es del 5 %. Nada más.')
  })

  it('drops marks out of range, list bullets and a mark still streaming', () => {
    const parts = claims('- Uno [9]\n- Dos [1]\n- Tres [', 1)
    expect(parts.filter((p) => p.refs)).toEqual([{ text: 'Dos', refs: [1] }])
    expect(parts.at(-1).text).toBe('\n- Tres ')
  })

  it('makes one source of the passages of one page, numbered by first use', () => {
    const ps = [P('a', 14), P('b', 41), P('a', 14)]
    const s = sources(claims('X [2]. Y [3][1]. Z [F].', 3), ps)
    expect(s.map((x) => [x.key, x.nums, x.num])).toEqual([['b|41', [2], 1], ['a|14', [3, 1], 2], ['F', ['F'], 3]])
  })

  it('quotes the sentence that shares most with the claim', () => {
    const text = '12.1. Garantías\nSe exige garantía.\n12.2. Solvencia económica\nVolumen anual de negocios mínimo de 450.000 euros referido al mejor ejercicio.'
    const ex = excerpt(text, 'un volumen anual de negocios mínimo de 450.000 €')
    expect(ex.text).toBe('…Volumen anual de negocios mínimo de 450.000 euros referido al mejor ejercicio')
  })

})
