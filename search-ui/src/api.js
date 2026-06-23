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
