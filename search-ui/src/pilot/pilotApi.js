// search-ui/src/pilot/pilotApi.js — client for the document pilot's read-only API (/api/pilot)
import { buildQuery } from '../api.js'

const BASE = (import.meta.env.VITE_API_BASE || '/placsprag').replace(/\/$/, '') + '/api/pilot'

async function get(path, params = {}) {
  const qs = buildQuery(params)
  const r = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}

export const overview = () => get('/overview')
export const listTenders = (params) => get('/tenders', params)
export const getTender = (id) => get(`/tenders/${encodeURIComponent(id)}`)
export const getTenderGraph = (id) => get(`/tenders/${encodeURIComponent(id)}/graph`)
export const getNode = (id) => get('/node', { id })
export const getCompany = (id) => get(`/companies/${encodeURIComponent(id)}`)
export const ask = (params) => get('/ask', params)
export const getDocument = (sha, tender, start = 0, limit = 40) => get(`/documents/${sha}`, { tender, start, limit })
export const corpusGraph = () => get('/graph')
export const health = () => get('/health')
export const fileUrl = (sha, page) => `${BASE}/file/${sha}${page ? `#page=${page}` : ''}`
