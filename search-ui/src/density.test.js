import { describe, it, expect } from 'vitest'
import { linearPos, linearValue, densityPath } from './density.js'

describe('density helpers', () => {
  it('maps value to [0,1] and back', () => {
    expect(linearPos(50, 0, 100)).toBeCloseTo(0.5)
    expect(linearValue(0.5, 0, 100)).toBeCloseTo(50)
  })
  it('clamps out-of-range positions', () => {
    expect(linearPos(-10, 0, 100)).toBe(0)
    expect(linearPos(200, 0, 100)).toBe(1)
  })
  it('returns empty path for no data', () => {
    expect(densityPath([], 100, 30)).toBe('')
  })
  it('builds a closed area path spanning the width', () => {
    const d = densityPath([1, 3, 2], 100, 30)
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d).toContain('100')           // reaches full width
  })
})
