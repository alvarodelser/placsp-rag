import { describe, it, expect, vi, afterEach } from 'vitest'
import { buildQuery, facets } from './api.js'

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

afterEach(() => vi.restoreAllMocks())

describe('facets()', () => {
  it('GETs /api/facets with serialized params and returns json', async () => {
    const body = { total: 5, nuts: { ES30: 5 }, dates: { publication: [], plazo: [] } }
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      { ok: true, json: () => Promise.resolve(body) })
    const out = await facets({ cpv: ['45'], status: ['PUB'] })
    expect(out).toEqual(body)
    const url = spy.mock.calls[0][0]
    expect(url).toContain('/api/facets?')
    expect(url).toContain('cpv=45')
    expect(url).toContain('status=PUB')
  })
})
