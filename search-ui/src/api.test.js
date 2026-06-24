import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { buildQuery, sendFeedback, removeFeedback, facets } from './api.js'

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

describe('sendFeedback', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, app_version: 'abc' }),
    })
  })

  it('POSTs the feedback payload as JSON to /api/feedback', async () => {
    const payload = {
      search_id: 's1', session_id: 'sess1', query: 'obras', mode: 'hybrid',
      filters: { cpv: ['45'] },
      results: [{ id: 'a', rank: 0, score: 0.9 }],
      result_id: 'a',
    }
    const res = await sendFeedback(payload)
    expect(res.app_version).toBe('abc')
    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/feedback$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(opts.body)).toEqual(payload)
  })
})

describe('removeFeedback', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
  })

  it('DELETEs the search_id + result_id as JSON', async () => {
    await removeFeedback({ search_id: 's1', result_id: 'a' })
    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/feedback$/)
    expect(opts.method).toBe('DELETE')
    expect(JSON.parse(opts.body)).toEqual({ search_id: 's1', result_id: 'a' })
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
