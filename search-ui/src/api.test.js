import { describe, it, expect } from 'vitest'
import { buildQuery } from './api.js'

describe('buildQuery', () => {
  it('omits empty values', () => {
    expect(buildQuery({ q: 'obras', mode: 'hybrid', cpv: [], status: '' }))
      .toBe('q=obras&mode=hybrid')
  })
  it('repeats array params', () => {
    expect(buildQuery({ cpv: ['45', '72'] })).toBe('cpv=45&cpv=72')
  })
  it('encodes values', () => {
    expect(buildQuery({ q: 'obras públicas' })).toBe('q=obras%20p%C3%BAblicas')
  })
})
