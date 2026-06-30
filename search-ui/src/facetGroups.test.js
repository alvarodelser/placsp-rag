import { describe, it, expect } from 'vitest'
import {
  RESULT_GROUPS, TYPE_GROUPS, PROC_GROUPS, GROUPS_BY_FIELD,
  groupActive, groupCount, toggleGroup, toggleCode, findGroup,
} from './facetGroups.js'

describe('facetGroups config', () => {
  it('maps the agreed code sets per facet', () => {
    const codes = (groups) => groups.flatMap((g) => g.codes).sort()
    expect(codes(RESULT_GROUPS)).toEqual(['1', '10', '11', '2', '3', '4', '5', '6', '7', '8', '9'].sort())
    expect(codes(TYPE_GROUPS)).toEqual(['1', '2', '21', '22', '3', '31', '32', '40', '50', '7', '8'].sort())
    expect(codes(PROC_GROUPS)).toEqual(['1', '10', '100', '11', '12', '13', '2', '3', '4', '5', '6', '7', '8', '9', '999'].sort())
  })

  it('assigns every code to exactly one group (no overlap)', () => {
    for (const groups of [RESULT_GROUPS, TYPE_GROUPS, PROC_GROUPS]) {
      const all = groups.flatMap((g) => g.codes)
      expect(new Set(all).size).toBe(all.length)
    }
  })

  it('marks Procedimiento "Otros" as off-axis', () => {
    const otros = PROC_GROUPS.find((g) => g.label === 'Otros')
    expect(otros.axis).toBe(false)
    expect(PROC_GROUPS.filter((g) => g.axis !== false)).toHaveLength(6)
  })
})

describe('group options (granular sub-codes with codelist labels)', () => {
  it('exposes each code with its human label', () => {
    const adj = RESULT_GROUPS.find((g) => g.key === 'adj')
    expect(adj.options).toContainEqual({ code: '1', label: 'Adjudicado Provisionalmente' })
    expect(adj.options).toContainEqual({ code: '9', label: 'Formalizado' })
    const obras = TYPE_GROUPS.find((g) => g.key === 'obras')
    expect(obras.options).toContainEqual({ code: '31', label: 'Concesión de Obras Públicas' })
    const negoc = PROC_GROUPS.find((g) => g.key === 'negoc')
    expect(negoc.options).toContainEqual({ code: '5', label: 'Diálogo competitivo' })
  })
  it('keeps options aligned with codes', () => {
    for (const groups of [RESULT_GROUPS, TYPE_GROUPS, PROC_GROUPS]) {
      for (const g of groups) {
        expect(g.options.map((o) => o.code)).toEqual(g.codes)
      }
    }
  })
})

describe('toggleCode', () => {
  it('adds a single code when absent', () => {
    expect(toggleCode('9', ['1']).sort()).toEqual(['1', '9'])
  })
  it('removes a single code when present, leaving siblings', () => {
    expect(toggleCode('1', ['1', '2', '8'])).toEqual(['2', '8'])
  })
  it('tolerates empty input', () => {
    expect(toggleCode('1', undefined)).toEqual(['1'])
  })
})

describe('groupActive', () => {
  const g = { codes: ['1', '2', '8'] }
  it('is active only when every code is selected', () => {
    expect(groupActive(g, ['1', '2', '8'])).toBe(true)
    expect(groupActive(g, ['1', '2', '8', '9'])).toBe(true)
  })
  it('is inactive for partial or empty selection', () => {
    expect(groupActive(g, ['1', '2'])).toBe(false)
    expect(groupActive(g, [])).toBe(false)
    expect(groupActive(g, undefined)).toBe(false)
  })
})

describe('groupCount', () => {
  const g = { codes: ['1', '2', '8'] }
  it('sums the counts of its codes', () => {
    expect(groupCount(g, { '1': 5, '2': 3, '8': 2 })).toBe(10)
  })
  it('treats missing codes as zero', () => {
    expect(groupCount(g, { '1': 5 })).toBe(5)
  })
  it('returns null when no code has a count', () => {
    expect(groupCount(g, {})).toBeNull()
    expect(groupCount(g, undefined)).toBeNull()
  })
})

describe('toggleGroup', () => {
  const g = { codes: ['1', '2', '8'] }
  it('adds the full code set when inactive', () => {
    expect(toggleGroup(g, []).sort()).toEqual(['1', '2', '8'])
  })
  it('removes all of its codes when active', () => {
    expect(toggleGroup(g, ['1', '2', '8'])).toEqual([])
  })
  it('completes a partial selection rather than clearing it', () => {
    expect(toggleGroup(g, ['1']).sort()).toEqual(['1', '2', '8'])
  })
  it('preserves codes from other groups', () => {
    expect(toggleGroup(g, ['99', '1', '2', '8']).sort()).toEqual(['99'])
    expect(toggleGroup(g, ['99']).sort()).toEqual(['1', '2', '8', '99'])
  })
  it('does not duplicate already-present codes', () => {
    const out = toggleGroup(g, ['1'])
    expect(new Set(out).size).toBe(out.length)
  })
})

describe('findGroup', () => {
  it('finds the group owning a code for a field', () => {
    expect(findGroup('result', '9').label).toBe('Adjudicado')
    expect(findGroup('contract_type', '31').label).toBe('Obras')
    expect(findGroup('procedure', '13').label).toBe('Negociado')
  })
  it('returns null for unknown field or code', () => {
    expect(findGroup('result', 'zzz')).toBeNull()
    expect(findGroup('cpv', '1')).toBeNull()
  })
  it('exposes groups by field', () => {
    expect(GROUPS_BY_FIELD.result).toBe(RESULT_GROUPS)
    expect(GROUPS_BY_FIELD.contract_type).toBe(TYPE_GROUPS)
    expect(GROUPS_BY_FIELD.procedure).toBe(PROC_GROUPS)
  })
})
