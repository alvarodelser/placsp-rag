import { describe, expect, it } from 'vitest'
import { reflow, lineKey, lineKeyRanges, blocks, markup } from './doctext.js'

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

describe('blocks', () => {
  const kinds = (t) => blocks(t).map((b) => `${b.type}:${t.slice(b.a, b.b).trim().replace(/\s+/g, ' ')}`)
  it('lays a notice out as headings and label/value fields', () => {
    const t = 'Anuncio de adjudicación\nNúmero de Expediente\n 192/2026\n\nEntidad Adjudicadora\nEmpresa Municipal de la Vivienda\nTeléfono \n +34 915168770\n'
    expect(kinds(t)).toEqual(['heading:Anuncio de adjudicación', 'field:Número de Expediente 192/2026',
      'heading:Entidad Adjudicadora', 'para:Empresa Municipal de la Vivienda', 'field:Teléfono +34 915168770'])
  })
  it('keeps pages, numbered headings, items and paragraphs apart', () => {
    const t = '[Página 2]\n1.2 División en lotes\nEl contrato no se divide en lotes porque\nlo impide su objeto.\n\n• Primera condición\nCLÁUSULA TERCERA'
    expect(kinds(t)).toEqual(['page:[Página 2]', 'heading:1.2 División en lotes',
      'para:El contrato no se divide en lotes porque lo impide su objeto.', 'item:• Primera condición', 'heading:CLÁUSULA TERCERA'])
    expect(blocks(t)[0].page).toBe(2)
  })
})

describe('markdown from the layout pass', () => {
  const t = '## **CLÁUSULA 8. SOLVENCIA**\n|N.º|LICITADORES|PUNTOS<br>TOTALES|\n|---|---|---|\n|9|JOGOSA OBRAS, S.L.U.|95,27|\n|1|ACTUACIONES, SL|95,00|\nTexto <u>subrayado</u> y **negrita** con `código`.'
  it('keeps tables and headings as their own lines', () => {
    expect(reflow(t)).toBe(t)
  })
  it('reads tables as rows of cells, the rule marking the header', () => {
    const tb = blocks(t).find((b) => b.type === 'table')
    expect(tb.rows.map((r) => r.cells.map((c) => t.slice(c.a, c.b)))).toEqual([
      ['N.º', 'LICITADORES', 'PUNTOS<br>TOTALES'], ['9', 'JOGOSA OBRAS, S.L.U.', '95,27'], ['1', 'ACTUACIONES, SL', '95,00']])
    expect(tb.rows.map((r) => !!r.head)).toEqual([true, false, false])
    expect(blocks(t)[0]).toMatchObject({ type: 'heading', level: 2 })
  })
  it('hides the markers without moving a character', () => {
    const { hide, strong, br } = markup(t)
    const shown = [...t].filter((_, i) => !hide.some((h) => i >= h.a && i < h.b)).join('')
    expect(shown).toContain('CLÁUSULA 8. SOLVENCIA\n|N.º|LICITADORES|PUNTOSTOTALES|')
    expect(shown).toContain('Texto subrayado y negrita con código.')
    expect(strong.map((s) => t.slice(s.a, s.b).replace(/<\/?u>/g, ''))).toEqual(['CLÁUSULA 8. SOLVENCIA', 'negrita', 'subrayado'])
    expect(br.map((i) => t.slice(i, i + 4))).toEqual(['<br>'])
  })
  it('folds furniture by the ranges the pipeline found', () => {
    const f = 'cuerpo del pliego\nCód. Validación: 7XK | Página 2 de 9\nsigue aquí'
    const a = f.indexOf('Cód'), b = f.indexOf('\nsigue')
    expect(reflow(f, null, [{ a, b }])).toBe(f)
  })
})
