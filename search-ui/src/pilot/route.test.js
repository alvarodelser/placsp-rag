import { parse, isPilot, trail, track, previous } from './route.js'

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

describe('trail', () => {
  it('names where a route is, from the start', () => {
    const names = { 't:1': { name: 'Limpieza' }, 'd:abc': { name: 'PCAP · doc 2' }, 'c:org:x': { name: 'Clece', label: 'Company' } }
    expect(trail(parse('#/pilot'), names).map((s) => s.name)).toEqual(['Inicio'])
    expect(trail(parse('#/pilot/t/1'), names).map((s) => s.name)).toEqual(['Inicio', 'Limpieza'])
    expect(trail(parse('#/pilot/t/1?tab=lotes'), names).map((s) => s.name)).toEqual(['Inicio', 'Limpieza', 'Lotes'])
    expect(trail(parse('#/pilot/t/1/d/abc'), names).map((s) => [s.name, s.to])).toEqual([
      ['Inicio', ''], ['Limpieza', '/t/1'], ['Documentos', '/t/1?tab=documentos'], ['PCAP · doc 2', '/t/1/d/abc']])
    expect(trail(parse(`#/pilot/c/${encodeURIComponent('org:x')}`), names)[1]).toMatchObject({ label: 'Company', name: 'Clece' })
  })
  it('falls back to the id until the page has loaded its name', () => {
    expect(trail(parse('#/pilot/t/9'))[1].name).toBe('9')
  })
})

describe('track / previous', () => {
  it('knows the page before, and forgets it on the way back', () => {
    track('#/pilot'); track('#/pilot/t/1'); track('#/pilot/t/1/d/a')
    expect(previous()).toBe('#/pilot/t/1')
    track('#/pilot/t/1')
    expect(previous()).toBe('#/pilot')
  })
})
