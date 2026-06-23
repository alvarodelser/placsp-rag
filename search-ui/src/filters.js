// Pure filter helpers (no React). Maps UI filter state to API params, defines
// the cleared (EMPTY) and default (EXPLORE) shapes, and derives the active
// filter list used by the chip row and rail badges.

export const EMPTY = {
  cpv: [], nuts: [], status: [], result: [], contract_type: [], procedure: [],
  pub_from: '', pub_to: '', budget_min: '', budget_max: '', open_only: false,
  sort: '',
}

export const EXPLORE = {
  ...EMPTY,
  status: ['PUB', 'PRE'],
  sort: 'publication_date desc',
}

export function todayISO(date = new Date()) {
  return date.toISOString().slice(0, 10)
}

export function filtersToParams(filters) {
  const out = {}
  for (const [k, v] of Object.entries(filters)) {
    if (k === 'open_only') continue
    if (v == null || v === '') continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  if (filters.open_only) out.deadline_from = todayISO()
  return out
}

export function presetRange(name, today = new Date()) {
  if (name === 'all') return { pub_from: '', pub_to: '' }
  const d = new Date(today.getTime())
  if (name === 'month') d.setUTCMonth(d.getUTCMonth() - 1)
  else if (name === 'quarter') d.setUTCMonth(d.getUTCMonth() - 3)
  else if (name === 'year') d.setUTCFullYear(d.getUTCFullYear() - 1)
  return { pub_from: todayISO(d), pub_to: todayISO(today) }
}

const LIST_FIELDS = ['cpv', 'nuts', 'status', 'result', 'contract_type', 'procedure']

export function activeFilterList(filters) {
  const out = []
  for (const f of LIST_FIELDS) {
    for (const v of filters[f] || []) out.push({ field: f, value: v })
  }
  if (filters.pub_from || filters.pub_to) {
    out.push({ field: 'dates', value: `${filters.pub_from || '…'} – ${filters.pub_to || '…'}` })
  }
  if (filters.open_only) out.push({ field: 'open_only', value: 'Plazo abierto' })
  if (filters.budget_min || filters.budget_max) {
    out.push({ field: 'budget', value: `${filters.budget_min || '0'} – ${filters.budget_max || '∞'}` })
  }
  return out
}
