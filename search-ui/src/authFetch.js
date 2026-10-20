// search-ui/src/authFetch.js — the API is invite-only: every /api call needs the session cookie,
// and the access token lasts ACCESS_TOKEN_MINUTES. Rather than each client handling that, fetch is
// wrapped once (main.jsx): a 401 from /api (not from /api/auth/*) refreshes the session and repeats
// the call once; if the refresh fails too, an 'auth:expired' event sends the reader to sign in.

export function installAuthRetry(base) {
  const plain = window.fetch.bind(window)
  let refreshing = null
  const refresh = () => (refreshing ||= plain(`${base}/api/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then((r) => r.ok).catch(() => false).finally(() => { setTimeout(() => { refreshing = null }, 0) }))

  window.fetch = async (input, init) => {
    const r = await plain(input, init)
    const url = typeof input === 'string' ? input : input?.url || ''
    const path = url.startsWith('http') ? new URL(url).pathname : url
    if (r.status !== 401 || !path.startsWith(`${base}/api/`) || path.startsWith(`${base}/api/auth/`)) return r
    if (await refresh()) return plain(input, init)
    window.dispatchEvent(new Event('auth:expired'))
    return r
  }
}
