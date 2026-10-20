// search-ui/src/pilot/labels.js — names and colours for the pilot graph's node types and roles

export const NODE = {
  Tender:              { es: 'Expediente',           color: '#374151' },
  Organization:        { es: 'Organización',         color: '#16a34a' },
  Company:             { es: 'Empresa',              color: '#16a34a' },
  Authority:           { es: 'Órgano de contratación', color: '#2563eb' },
  JointVenture:        { es: 'UTE',                  color: '#16a34a' },
  Lot:                 { es: 'Lote',                 color: '#c47d0e' },
  AwardCriterion:      { es: 'Criterio',             color: '#8b5cf6' },
  Requirement:         { es: 'Requisito',            color: '#d14d72' },
  Qualification:       { es: 'Acreditación',         color: '#d14d72' },
  Guarantee:           { es: 'Garantía',             color: '#64748b' },
  ExecutionCondition:  { es: 'Condición ejecución',  color: '#64748b' },
  Bid:                 { es: 'Oferta',               color: '#1a7a4d' },
  Result:              { es: 'Resultado',            color: '#1a7a4d' },
  Contract:            { es: 'Contrato',             color: '#1a7a4d' },
  Modification:        { es: 'Modificación',         color: '#b45309' },
  Penalty:             { es: 'Penalidad',            color: '#64748b' },
  Deliverable:         { es: 'Entregable',           color: '#64748b' },
  TeamProfile:         { es: 'Perfil equipo',        color: '#64748b' },
  TechnicalRequirement:{ es: 'Requisito técnico',    color: '#64748b' },
  Document:            { es: 'Documento',            color: '#475569' },
  Notice:              { es: 'Anuncio',              color: '#94a3b8' },
  Sector:              { es: 'Sector (CPV)',         color: '#a3a3a3' },
}
// Never drawn on a graph: they are read in the tender's lists, and on a map they only crowd it.
export const NOT_DRAWN = new Set(['Requirement', 'TechnicalRequirement', 'Qualification', 'Sector'])

export const nodeInfo = (label) => NODE[label] || { es: label, color: '#94a3b8' }

export const ROLE = {
  PCAP: 'PCAP', PPT: 'PPT', 'PCAP+PPT': 'PCAP+PPT', Annex: 'Anexo', TechnicalAnnex: 'Anexo técnico',
  ProjectDocument: 'Proyecto', PreparatoryDocument: 'Preparatorio', PriorNotice: 'Anuncio previo',
  TenderNotice: 'Anuncio licitación', Clarification: 'Aclaración', BoardMinutes: 'Acta mesa',
  ValuationReport: 'Informe valoración', AbnormalBidReport: 'Informe baja anormal', AwardProposal: 'Propuesta adj.',
  AwardResolution: 'Resolución adj.', AwardNotice: 'Anuncio adj.', CancellationDocument: 'Desistimiento/renuncia',
  AppealDocument: 'Recurso', ContractDocument: 'Contrato', FormalizationNotice: 'Anuncio formalización',
  ModificationDocument: 'Modificación', ModificationNotice: 'Anuncio modificación', Other: 'Otro',
}
export const roleEs = (r) => ROLE[r] || r || '—'

export const COMPANY_ROLE = {
  winner: 'adjudicataria', bidder: 'licitadora', contractor: 'contratista', ute_member: 'miembro UTE',
  authority: 'órgano de contratación', mentioned: 'mencionada',
}

// Where a tender stands, from its feed status and its deadline: open (offers can still be sent),
// in evaluation, closed (awarded, resolved…) or void. `cls` is the badge's class.
export function tenderState(t) {
  const x = (t?.status || '').toUpperCase()
  const deadline = typeof t?.deadline === 'string' ? t.deadline : t?.deadline?.date
  const past = deadline ? new Date(`${deadline.slice(0, 10)}T23:59:59`) < new Date() : false
  if (/ANULAD|DESIERT|DESIST|RENUNCIA/.test(x)) return { key: 'void', cls: 'st-void', es: x.includes('DESIERT') ? 'Desierto' : 'Anulado' }
  if (/PLAZO|PUBLICAD/.test(x)) return past ? { key: 'pending', cls: 'st-pending', es: 'Plazo cerrado' } : { key: 'open', cls: 'st-open', es: 'Abierto' }
  if (/PENDIENTE|EVALUACI/.test(x)) return { key: 'pending', cls: 'st-pending', es: 'En evaluación' }
  if (x.includes('ADJUDIC')) return { key: 'done', cls: 'st-done', es: 'Adjudicado' }
  if (x.includes('RESUEL')) return { key: 'done', cls: 'st-done', es: 'Resuelto' }
  return x ? { key: 'done', cls: 'st-done', es: x.charAt(0) + x.slice(1).toLowerCase() } : null
}

export const CHANNEL = {
  placsp_mayores: 'Mayores', externos_mayores: 'Externos', placsp_menores: 'Menores', propios: 'Encargos',
}

// The short title the pipeline wrote for a long name; before it, the name without its translation
// ("Obra X / Obra X" in Valencian, Catalan, Galician or Basque keeps the first half).
export function shortTitle(t) {
  if (t.short_title) return t.short_title
  const name = (t.name || '').trim()
  const parts = name.split(/\s+\/\s+/).filter(Boolean)
  return parts.length === 2 ? parts[0] : name
}

// An organization's name as the graph shows it: without the body inside it that signs the contract
// ("Alcaldía del Ayuntamiento de Coaña" is Coaña's council), without the kind of entity or the legal
// form, and with the usual abbreviations. The full name stays in the panels.
const ORGAN = /^(alcald[ií]a|presidencia|pleno|junta de gobierno( local)?|mesa de contrataci[oó]n|[oó]rgano de contrataci[oó]n|gerencia)\s+(del?|de la)\s+/i
const KIND = /^(organismo aut[oó]nomo( local)?|entidad p[uú]blica empresarial|sociedad mercantil( local| estatal)?|empresa municipal)\s+(de\s+)?/i
const ABBR = [
  [/^(excmo\.?|excelent[ií]simo|ilmo\.?|ilustr[ií]simo)\s+/i, ''],
  [/^ayuntamiento\s+(de\s+)?/i, 'Ayto. '],
  [/^diputaci[oó]n provincial\s+(de\s+)?/i, 'Dip. '],
  [/^diputaci[oó]n\s+(de\s+)?/i, 'Dip. '],
  [/^mancomunidad\s+(de\s+)?/i, 'Manc. '],
  [/^universidad\s+(de\s+)?/i, 'Univ. '],
  [/^consejer[ií]a\s+de\s+/i, 'Cons. '],
  [/^ministerio\s+de\s+/i, 'Min. '],
]
const LEGAL = /[\s,]+(s\.?\s?a\.?\s?u\.?|s\.?\s?l\.?\s?u\.?|s\.?\s?l\.?\s?p\.?|s\.?\s?a\.?|s\.?\s?l\.?|s\.?\s?coop\.?( and\.?)?|sociedad (an[oó]nima|limitada|cooperativa)( unipersonal| laboral)?|sociedad unipersonal)\.?$/i
const LOWER = new Set(['de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'para', 'en', 'a', 'con', 'por'])

export function shortOrg(name, max = 30) {
  let s = (name || '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim()
  for (let i = 0; i < 4; i++) {                    // a legal form can be written twice ("S.A., Sociedad Unipersonal")
    const t = s.replace(LEGAL, '').replace(/[\s,.]+$/, '')
    if (t === s || !t) break
    s = t
  }
  s = s.replace(ORGAN, '').replace(KIND, '')
  for (const [re, to] of ABBR) s = s.replace(re, to)
  // Shouting is not a name: ESPUBLICO SERVICIOS → Espublico Servicios; short words (UTE, TIC) stay.
  if (s === s.toUpperCase() && /[A-ZÁÉÍÓÚÑ]{4}.*\s.*[A-ZÁÉÍÓÚÑ]{4}/.test(s)) {
    s = s.toLowerCase().split(' ').map((w, i) => (i && LOWER.has(w) ? w
      : w.length <= 3 && !LOWER.has(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1))).join(' ')
  }
  if (s.length <= max) return s
  let cut = s.slice(0, max - 1)
  if (cut.lastIndexOf(' ') > max / 2) cut = cut.slice(0, cut.lastIndexOf(' '))
  const words = cut.split(' ')
  while (words.length > 1 && LOWER.has(words[words.length - 1].toLowerCase())) words.pop()   // not "Servicios para la…"
  return `${words.join(' ').replace(/[\s,.]+$/, '')}…`
}

// What a date is, for its hover: a node's date fields (label, explanation) and where a document's
// date comes from (order.py's date_source).
export const DATE_FIELD = {
  published: ['Publicado', 'Primera publicación de un anuncio de este expediente en la Plataforma de Contratación.'],
  deadline: ['Fin de ofertas', 'Último día para presentar ofertas.'],
  date: ['Adjudicación', 'Fecha del acuerdo de adjudicación, según el anuncio.'],
  signed_date: ['Formalización', 'Fecha en que se formalizó (firmó) el contrato.'],
  start: ['Inicio', 'Fecha de inicio de la ejecución del contrato.'],
  effective_date: ['Fecha', 'Fecha con la que se ordena este documento en el expediente.'],
}
const DATE_SOURCE = {
  published: 'Fecha en que se publicó este documento en la Plataforma de Contratación.',
  notice: 'Fecha del anuncio con el que se publicó este documento.',
  stage: 'El documento no trae fecha propia: es la de la fase del expediente a la que pertenece.',
  none: 'No se conoce la fecha de este documento.',
}
export const docDateTip = (d) => DATE_SOURCE[d?.date_source] || 'Fecha del documento en el expediente.'

// Every date in the pilot reads the same: dd/mm/aaaa. Takes '2026-01-10', a timestamp, or {date}.
export function dmy(d) {
  const x = typeof d === 'string' ? d : d?.date
  if (!x || !/^\d{4}-\d{2}-\d{2}/.test(x)) return x || ''
  return x.slice(0, 10).split('-').reverse().join('/')
}

// A graph relation as the panels name it, outgoing and (with " ←", as the node endpoint marks it)
// incoming. Unknown relations fall back to the raw name, lower-cased.
const REL = {
  HAS_LOT: ['Lotes', 'Expediente'], HAS_CRITERION: ['Criterios', 'Lote'], REQUIRES: ['Requisitos', 'Exigido en'],
  INCLUDES: ['Incluye', 'Incluido en'], HAS_RESULT: ['Resultado', 'Lote'], HAS_NOTICE: ['Anuncios', 'Expediente'],
  HAS_CONDITION: ['Condiciones', 'Expediente'], WINNER: ['Adjudicataria', 'Adjudicaciones'], RESULTED_IN: ['Resultó en', 'Resultado de'],
  DETAILED_BY: ['Detallado en', 'Detalla'], ACCEPTS: ['Acepta', 'Aceptado por'], PUBLISHED: ['Publicó', 'Publicado por'],
  HAS_CONTRACT: ['Contrato', 'Expediente'], CONTRACT_FOR: ['Contrato de', 'Contratos'], SUBMITTED_BY: ['Presentada por', 'Ofertas'],
  RECEIVED_BID: ['Ofertas recibidas', 'Oferta a'], BID_FOR: ['Oferta a', 'Ofertas recibidas'], HAS_DOCUMENT: ['Documentos', 'Expediente'],
  CLASSIFIED_AS: ['Sector', 'Expedientes del sector'], TENDERED: ['Licitó', 'Licitadoras'], LOCATED_IN: ['Lugar', 'Expedientes en'],
  MENTIONED_IN: ['Mencionado en', 'Menciona'], BIDDER: ['Licitadora', 'Licitó en'], CONTRACTOR: ['Contratista', 'Contratos'],
}
export function relEs(key) {
  const incoming = key.endsWith(' ←')
  const base = key.replace(/ ←$/, '')
  return REL[base]?.[incoming ? 1 : 0] || base.toLowerCase().replace(/_/g, ' ')
}

// A node's raw property, named for the panel; unknown ones are shown as written, without underscores.
const FIELD = {
  procedure: 'Procedimiento', contract_type: 'Tipo de contrato', subtype: 'Subtipo', nif: 'NIF', number: 'Número',
  points: 'Puntos', amount: 'Importe', budget: 'Presupuesto base', value: 'Valor estimado', role: 'Papel', pages: 'Páginas',
  filename: 'Archivo', ext: 'Formato', seq: 'Orden', stage: 'Fase', pct: 'Porcentaje', unit: 'Unidad', text: 'Texto',
  winner: 'Adjudicataria', price: 'Precio', outcome: 'Resultado', bids_received: 'Ofertas recibidas', nuts: 'NUTS', cpv: 'CPV',
  sara: 'Regulación armonizada', kind: 'Tipo', kinds: 'Tipo', place: 'Lugar', duration: 'Duración',
}
export const fieldEs = (k) => FIELD[k] || k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

// An organization's kinds (the graph's, or the search's lower-case ones) in Spanish.
const ORG_KIND = { Company: 'Empresa', company: 'Empresa', ContractingAuthority: 'Órgano de contratación', authority: 'Órgano de contratación',
  JointVenture: 'UTE', Organization: 'Organización' }
export const orgKindEs = (k) => ORG_KIND[k] || k
