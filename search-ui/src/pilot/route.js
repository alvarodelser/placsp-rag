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

// Like go(), without a new history entry: a tender's tab changes the address (it can be linked
// and is kept when coming back) but "Atrás" still goes to the page before.
export function replace(path) {
  const url = new URL(window.location.href)
  url.hash = `#/pilot${path}`
  replacing = true
  window.location.replace(url.href)
}

// The pages seen in this visit, oldest first, so "Atrás" knows whether there is a page before
// (and which) or should go up a level instead.
let replacing = false
const seen = []
export function track(hash) {
  if (replacing) { replacing = false; if (seen.length) { seen[seen.length - 1] = hash; return } }
  if (seen[seen.length - 2] === hash) seen.pop()
  else if (seen[seen.length - 1] !== hash) seen.push(hash)
}
export const previous = () => seen[seen.length - 2] || null

export const TENDER_TABS = [['resumen', 'Resumen'], ['lotes', 'Lotes'], ['documentos', 'Documentos'], ['preguntar', 'Preguntar']]
const TAB_ES = Object.fromEntries(TENDER_TABS)

// Where a route is, as a trail from the pilot's start: each step its kind (as the graph names and
// colours it), its name and where it goes; the last step is the page itself. `names` holds what the
// pages have loaded: t:<id> → {name}, c:<id> → {name, label}, d:<sha> → {name}.
export function trail(route, names = {}) {
  const home = { label: 'Home', name: 'Inicio', to: '' }
  if (route.kind === 't') {
    const t = { label: 'Tender', name: names[`t:${route.id}`]?.name || route.id, to: `/t/${route.id}` }
    if (route.doc) {
      return [home, t, { name: 'Documentos', to: `/t/${route.id}?tab=documentos` },
        { label: 'Document', name: names[`d:${route.doc}`]?.name || 'Documento', to: `/t/${route.id}/d/${route.doc}` }]
    }
    const tab = route.params.tab
    return tab && tab !== 'resumen' && TAB_ES[tab] ? [home, t, { name: TAB_ES[tab], to: `/t/${route.id}?tab=${tab}` }] : [home, t]
  }
  if (route.kind === 'c') {
    const c = names[`c:${route.id}`]
    return [home, { label: c?.label || 'Organization', name: c?.name || route.id, to: `/c/${encodeURIComponent(route.id)}` }]
  }
  return [home]
}
