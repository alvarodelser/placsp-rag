const BASE = (import.meta.env.VITE_API_BASE || '/placsprag').replace(/\/$/, '')

export function buildQuery(params) {
  const parts = []
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      for (const v of value) {
        if (v == null || v === '') continue
        parts.push(`${key}=${encodeURIComponent(v)}`)
      }
    } else {
      parts.push(`${key}=${encodeURIComponent(value)}`)
    }
  }
  return parts.join('&')
}

export async function search(params) {
  const url = `${BASE}/api/search?${buildQuery(params)}`
  const r = await fetch(url)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}

export async function facets(params) {
  const url = `${BASE}/api/facets?${buildQuery(params)}`
  const r = await fetch(url)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}

async function feedbackRequest(method, body) {
  const r = await fetch(`${BASE}/api/feedback`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}

// Record a "relevant" judgment on one result. `payload` carries the search
// context (query/mode/filters + the shown results snapshot) plus the liked id.
export function sendFeedback(payload) {
  return feedbackRequest('POST', payload)
}

// Toggle a "relevant" judgment off.
export function removeFeedback({ search_id, result_id }) {
  return feedbackRequest('DELETE', { search_id, result_id })
}
