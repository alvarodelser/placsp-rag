import { parse, isPilot } from './route.js'

describe('pilot routes', () => {
  it('parses tender, company and ask routes', () => {
    expect(parse('#/pilot')).toEqual({ kind: 'home', id: null, params: {} })
    expect(parse('#/pilot/t/20497225')).toMatchObject({ kind: 't', id: '20497225' })
    expect(parse(`#/pilot/c/${encodeURIComponent('org:nif:A79365821')}`)).toMatchObject({ kind: 'c', id: 'org:nif:A79365821' })
    expect(parse('#/pilot/ask?q=solvencia%20econ%C3%B3mica')).toMatchObject({ kind: 'ask', params: { q: 'solvencia económica' } })
    expect(parse('#/pilot/t/20415863/d/abc?c=3&e=org%3Anif%3AX')).toMatchObject({ kind: 't', id: '20415863', doc: 'abc', params: { c: '3', e: 'org:nif:X' } })
  })
  it('only claims #/pilot hashes', () => {
    expect(isPilot('#/pilot/t/1')).toBe(true)
    expect(isPilot('')).toBe(false)
    expect(isPilot('#/')).toBe(false)
  })
})
