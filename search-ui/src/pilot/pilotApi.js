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
export const getNode = (id, chunks) => get('/node', chunks ? { id, chunks } : { id })
export const getCompany = (id) => get(`/companies/${encodeURIComponent(id)}`)
export const ask = (params) => get('/ask', params)

// A cited answer, streamed: NDJSON events (passages, token*, done | error) passed to onEvent.
export async function answer(params, onEvent, signal) {
  const r = await fetch(`${BASE}/answer?${buildQuery(params)}`, { signal })
  if (!r.ok) {
    const data = await r.json().catch(() => ({}))
    throw new Error(data.detail || r.statusText || 'request failed')
  }
  const reader = r.body.getReader(), dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf))
}
export const getDocument = (sha, tender, start = 0, limit = 40, entity = '') => get(`/documents/${sha}`, { tender, start, limit, entity })
export const docPreview = (sha, tender) => get(`/documents/${sha}/preview`, { tender, spans: 0 })
export const corpusGraph = (params) => get('/graph', params)
export const search = (params) => get('/search', params)
export const health = () => get('/health')
