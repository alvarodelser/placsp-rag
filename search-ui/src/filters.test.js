import { describe, it, expect } from 'vitest'
import { EMPTY, EXPLORE, todayISO, filtersToParams, presetRange, activeFilterList } from './filters.js'

describe('EXPLORE preset', () => {
  it('is PUB+PRE sorted latest, no deadline', () => {
    expect(EXPLORE.status).toEqual(['PUB', 'PRE'])
    expect(EXPLORE.sort).toBe('publication_date desc')
    expect(EXPLORE.open_only).toBe(false)
    expect(filtersToParams(EXPLORE)).toEqual({ status: ['PUB', 'PRE'], sort: 'publication_date desc' })
  })
})

describe('filtersToParams', () => {
  it('drops empties for EMPTY', () => {
    expect(filtersToParams(EMPTY)).toEqual({})
  })
  it('maps open_only to deadline_from', () => {
    const p = filtersToParams({ ...EMPTY, open_only: true })
    expect(p.deadline_from).toBe(todayISO())
    expect('open_only' in p).toBe(false)
  })
  it('keeps non-empty values', () => {
    expect(filtersToParams({ ...EMPTY, cpv: ['45'], budget_min: '1000' }))
      .toEqual({ cpv: ['45'], budget_min: '1000' })
  })
})

describe('presetRange', () => {
  const ref = new Date('2025-06-23T00:00:00Z')
  it('computes year/month windows in UTC', () => {
    expect(presetRange('year', ref)).toEqual({ pub_from: '2024-06-23', pub_to: '2025-06-23' })
    expect(presetRange('month', ref)).toEqual({ pub_from: '2025-05-23', pub_to: '2025-06-23' })
  })
  it('clears the range for "all"', () => {
    expect(presetRange('all', ref)).toEqual({ pub_from: '', pub_to: '' })
  })
})

describe('activeFilterList', () => {
  it('is empty for EMPTY', () => {
    expect(activeFilterList(EMPTY)).toEqual([])
  })
  it('lists each status value', () => {
    expect(activeFilterList(EXPLORE)).toEqual([
      { field: 'status', value: 'PUB' },
      { field: 'status', value: 'PRE' },
    ])
  })
  it('includes dates, budget and open_only entries', () => {
    const list = activeFilterList({ ...EMPTY, pub_from: '2024-01-01', open_only: true, budget_min: '1000' })
    expect(list.map((e) => e.field)).toEqual(['dates', 'open_only', 'budget'])
  })
})
