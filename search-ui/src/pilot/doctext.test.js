import { describe, expect, it } from 'vitest'
import { reflow, lineKey, lineKeyRanges } from './doctext.js'

describe('doctext', () => {
  it('joins lines a PDF broke mid-sentence and keeps the length', () => {
    const t = 'El objeto de este contrato es el mantenimiento al Ayuntamiento de Benabarre de la actual \nplataforma de administración electrónica.\n• Cumplimiento de las Leyes\n1.2 División en lotes'
    const r = reflow(t)
    expect(r.length).toBe(t.length)
    expect(r).toContain('actual  plataforma')
    expect(r).toContain('electrónica.\n•')
    expect(r).toContain('Leyes\n1.2')
  })

  it('keeps footers apart and turns symbol bullets into bullets', () => {
    const keys = new Set([lineKey('Ayuntamiento de Benabarre')])
    const t = 'es importante que los licitadores\nAyuntamiento de Benabarre\n\uF0B7 La custodia'
    const r = reflow(t, keys)
    expect(r).toBe('es importante que los licitadores\nAyuntamiento de Benabarre\n• La custodia')
  })

  it('reads a notice label with its value', () => {
    expect(reflow('Ponderación\n: 30\nCantidad Mínima\n: 0')).toBe('Ponderación : 30\nCantidad Mínima : 0')
  })

  it('finds the repeated lines by their key', () => {
    const t = 'texto\nDocumento firmado electrónicamente | Página 3 de 23\nmás'
    const keys = new Set([lineKey('Documento firmado electrónicamente | Página 1 de 23')])
    const [r] = lineKeyRanges(t, keys)
    expect(t.slice(r.a, r.b)).toBe('Documento firmado electrónicamente | Página 3 de 23')
  })
})
