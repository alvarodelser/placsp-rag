const BASE = (import.meta.env.VITE_API_BASE || '/placsprag').replace(/\/$/, '')

export async function search(q, mode = 'hybrid', k = 15) {
  const url = `${BASE}/api/search?q=${encodeURIComponent(q)}&mode=${mode}&k=${k}`
  const r = await fetch(url)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
  return data
}
