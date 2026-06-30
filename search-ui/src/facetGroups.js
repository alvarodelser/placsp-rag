/**
 * facetGroups — single source of truth for the simplified, grouped facets
 * (Resultado, Tipo, Procedimiento). One group card stands for a *set* of
 * granular API codes: clicking it toggles all of them, and its count is the
 * sum of its codes' counts. Imported by the workspace components and by
 * ActiveFilters (to collapse chips to one-per-group).
 */
import {
  Trophy, XCircle, Prohibit,
  Wrench, FileText, Package, Scales,
  ArrowsLeftRight, ListChecks, Gavel, Stack, Archive,
} from './icons.js'

// Resultado — 3 outcome cards (was 11 codes)
export const RESULT_GROUPS = [
  { key: 'adj', label: 'Adjudicado', Icon: Trophy,   color: 'green', codes: ['1', '2', '8', '9', '10', '11'] },
  { key: 'des', label: 'Desierto',   Icon: XCircle,  color: 'gray',  codes: ['3', '6', '7'] },
  { key: 'can', label: 'Cancelado',  Icon: Prohibit, color: 'red',   codes: ['4', '5'] },
]

// Tipo — 4 object-family cards (was 11 codes); concessions folded into parent
export const TYPE_GROUPS = [
  { key: 'obras', label: 'Obras',       Icon: Wrench,   codes: ['3', '31', '32'] },
  { key: 'serv',  label: 'Servicios',   Icon: FileText, codes: ['2', '21', '22'] },
  { key: 'sum',   label: 'Suministros', Icon: Package,  codes: ['1'] },
  { key: 'otros', label: 'Otros',       Icon: Scales,   codes: ['40', '50', '7', '8'] },
]

// Procedimiento — 6 cards on a concurrence axis + Otros off-axis (was 15 codes)
export const PROC_GROUPS = [
  { key: 'abierto',   label: 'Abierto',              Icon: ArrowsLeftRight, codes: ['1'] },
  { key: 'abierto_s', label: 'Abierto simplificado', Icon: ArrowsLeftRight, codes: ['9'] },
  { key: 'restr',     label: 'Restringido',          Icon: ListChecks,      codes: ['2'] },
  { key: 'negoc',     label: 'Negociado',            Icon: Gavel,           codes: ['3', '4', '5', '10', '11', '13'] },
  { key: 'deriv',     label: 'Derivados',            Icon: Stack,           codes: ['7', '12'] },
  { key: 'menor',     label: 'Contrato menor',       Icon: FileText,        codes: ['6'] },
  { key: 'otros',     label: 'Otros',                Icon: Archive,         codes: ['8', '100', '999'], axis: false },
]

export const GROUPS_BY_FIELD = {
  result:        RESULT_GROUPS,
  contract_type: TYPE_GROUPS,
  procedure:     PROC_GROUPS,
}

/** A group is active only when every one of its codes is selected. */
export function groupActive(group, value = []) {
  const v = value || []
  return group.codes.every((c) => v.includes(c))
}

/** Sum of the group's code counts; null when none of them have a count. */
export function groupCount(group, counts = {}) {
  const c = counts || {}
  let sum = 0
  let seen = false
  for (const code of group.codes) {
    if (c[code] != null) { sum += c[code]; seen = true }
  }
  return seen ? sum : null
}

/** Toggle the whole code set: remove all if active, else add the missing ones. */
export function toggleGroup(group, value = []) {
  const v = value || []
  if (groupActive(group, v)) return v.filter((c) => !group.codes.includes(c))
  const set = new Set(v)
  for (const c of group.codes) set.add(c)
  return [...set]
}

/** The group owning a granular code within a field, or null. */
export function findGroup(field, code) {
  const groups = GROUPS_BY_FIELD[field]
  if (!groups) return null
  return groups.find((g) => g.codes.includes(code)) || null
}
