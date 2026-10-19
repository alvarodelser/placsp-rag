// search-ui/src/pilot/labels.js — names and colours for the pilot graph's node types and roles

export const NODE = {
  Tender:              { es: 'Expediente',           color: '#4f46e5' },
  Organization:        { es: 'Organización',         color: '#0f8a7e' },
  Company:             { es: 'Empresa',              color: '#0f8a7e' },
  Authority:           { es: 'Órgano de contratación', color: '#0369a1' },
  JointVenture:        { es: 'UTE',                  color: '#0f8a7e' },
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
  Document:            { es: 'Documento',            color: '#3b6ea8' },
  Notice:              { es: 'Anuncio',              color: '#94a3b8' },
  Sector:              { es: 'Sector (CPV)',         color: '#a3a3a3' },
}
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

export const CHANNEL = {
  placsp_mayores: 'Mayores', externos_mayores: 'Externos', placsp_menores: 'Menores', propios: 'Encargos',
}
