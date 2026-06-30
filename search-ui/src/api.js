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

function tabFetcher(path) {
  return async (params) => {
    const r = await fetch(`${BASE}${path}?${buildQuery(params)}`)
    const data = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(data.detail || r.statusText || 'request failed')
    return data
  }
}

export const budgetDist   = tabFetcher('/api/facets/budget')
export const datesDist    = tabFetcher('/api/facets/dates')
export const locationDist = tabFetcher('/api/facets/location')
export const statusDist   = tabFetcher('/api/facets/status')
export const resultDist   = tabFetcher('/api/facets/result')
export const typeDist     = tabFetcher('/api/facets/type')
export const procedureDist= tabFetcher('/api/facets/procedure')
export const cpvDist      = tabFetcher('/api/facets/cpv')

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


// ── Auth ────────────────────────────────────────────────────────────────────

export async function authRegister({ email, password, display_name }) {
  const r = await fetch(`${BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password, display_name }),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'registration failed')
  return data
}

export async function authLogin(email, password) {
  const body = new URLSearchParams({ username: email, password })
  const r = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    credentials: 'include',
    body,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'login failed')
  return data
}

export async function authLogout() {
  const r = await fetch(`${BASE}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'logout failed')
  return data
}

export async function authMe() {
  const r = await fetch(`${BASE}/api/auth/me`, { credentials: 'include' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'not authenticated')
  return data
}

export async function authRefresh() {
  const r = await fetch(`${BASE}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
  return r.ok
}


// ── User saved items ────────────────────────────────────────────────────────

export async function saveItem({ item_id, syndication_id, title }) {
  const r = await fetch(`${BASE}/api/users/me/saved`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ item_id, syndication_id, title }),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'save failed')
  return data
}

export async function unsaveItem(itemId) {
  const r = await fetch(`${BASE}/api/users/me/saved/${encodeURIComponent(itemId)}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'unsave failed')
  return data
}

export async function listSaved({ offset = 0, limit = 50 } = {}) {
  const r = await fetch(
    `${BASE}/api/users/me/saved?${buildQuery({ offset, limit })}`,
    { credentials: 'include' },
  )
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'list failed')
  return data
}

export async function getSavedIds() {
  const r = await fetch(`${BASE}/api/users/me/saved/ids`, {
    credentials: 'include',
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'fetch ids failed')
  return data
}


// ── Pliegos ─────────────────────────────────────────────────────────────────

export async function getPliegos(syndicationId) {
  const r = await fetch(`${BASE}/api/pliegos/${encodeURIComponent(syndicationId)}`)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    if (r.status === 404) return null;
    throw new Error(data.detail || r.statusText || 'fetch pliegos failed')
  }
  return data
}

export async function triggerPliegosAnalysis(syndicationId) {
  const r = await fetch(`${BASE}/api/pliegos/${encodeURIComponent(syndicationId)}/analyze`, {
    method: 'POST',
    credentials: 'include',
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || r.statusText || 'failed to trigger analysis')
  return data
}

export async function getSavedAnalysis(itemId) {
  const r = await fetch(`${BASE}/api/users/me/saved/${encodeURIComponent(itemId)}/analysis`, {
    headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    if (r.status === 404) return null;
    throw new Error(data.detail || r.statusText || 'fetch analysis failed')
  }
  return data
}
