// search-ui/src/pilot/route.js — hash routes of the pilot viewer: #/pilot[?q=], #/pilot/t/<id>[/d/<sha>], #/pilot/c/<org>
import { useEffect, useState } from 'react'

export const isPilot = (hash = window.location.hash) => hash.startsWith('#/pilot')

export function go(path) {
  window.location.hash = `#/pilot${path}`
}

export function parse(hash) {
  const [path, qs] = hash.replace(/^#\/pilot/, '').split('?')
  const params = Object.fromEntries(new URLSearchParams(qs || ''))
  const [, kind, ...rest] = path.split('/')
  // #/pilot/t/<tender>/d/<sha>: a document of a tender, read with its annotations.
  if (kind === 't' && rest.length >= 3 && rest[1] === 'd') {
    return { kind, id: decodeURIComponent(rest[0]), doc: rest[2], params }
  }
  return { kind: kind || 'home', id: rest.length ? decodeURIComponent(rest.join('/')) : null, params }
}

export function useHash() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const on = () => setHash(window.location.hash)
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash
}
