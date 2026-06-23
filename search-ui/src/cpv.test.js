import { describe, it, expect } from 'vitest'
import { cpvLevel, cpvPath } from './cpv.js'

const MAP = {
  '45000000': 'Construcción',
  '45200000': 'Construcción completa',
  '45210000': 'Edificios',
  '45211000': 'Viviendas',
}

describe('cpvLevel', () => {
  it('returns significant digit length', () => {
    expect(cpvLevel('45000000')).toBe(2)
    expect(cpvLevel('45200000')).toBe(3)
    expect(cpvLevel('45210000')).toBe(4)
    expect(cpvLevel('45211000')).toBe(5)
  })
  it('strips a check-digit suffix', () => {
    expect(cpvLevel('45211000-1')).toBe(5)
  })
})

describe('cpvPath', () => {
  it('lists ancestor labels from division down, excluding self', () => {
    expect(cpvPath('45211000', MAP)).toEqual(['Construcción', 'Construcción completa', 'Edificios'])
  })
  it('returns empty for a division', () => {
    expect(cpvPath('45000000', MAP)).toEqual([])
  })
})
