import { describe, it, expect } from 'vitest'
import { columns } from './miller.js'

const MAP = {
  '45000000': 'Construcción', '72000000': 'TI',
  '45100000': 'Preparación', '45200000': 'Construcción general',
  '45210000': 'Edificios', '45220000': 'Caminos',
}

describe('miller columns', () => {
  it('column 0 lists divisions (2-digit) sorted', () => {
    const cols = columns([], MAP)
    expect(cols).toHaveLength(1)
    expect(cols[0].items.map((i) => i.code)).toEqual(['45000000', '72000000'])
    expect(cols[0].activeCode).toBe(null)
  })
  it('drilling adds a child column and marks the active code', () => {
    const cols = columns(['45000000'], MAP)
    expect(cols).toHaveLength(2)
    expect(cols[0].activeCode).toBe('45000000')
    expect(cols[1].items.map((i) => i.code)).toContain('45100000')
    expect(cols[1].items.map((i) => i.code)).toContain('45200000')
  })
})
