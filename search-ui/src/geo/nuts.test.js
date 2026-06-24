import { describe, it, expect } from 'vitest'
import { nutsLevel, truncate, aggregateByLevel } from './nuts.js'

describe('nuts helpers', () => {
  it('derives level from code length', () => {
    expect(nutsLevel('ES30')).toBe(2)
    expect(nutsLevel('ES300')).toBe(3)
  })
  it('truncates to a level', () => {
    expect(truncate('ES300', 2)).toBe('ES30')
    expect(truncate('ES300', 3)).toBe('ES300')
  })
  it('aggregates fine codes up to a level', () => {
    const counts = { ES300: 900, ES511: 100, ES512: 50 }
    expect(aggregateByLevel(counts, 2)).toEqual({ ES30: 900, ES51: 150 })
    expect(aggregateByLevel(counts, 3)).toEqual({ ES300: 900, ES511: 100, ES512: 50 })
  })
})
