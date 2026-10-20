// search-ui/src/pilot/cites.js — an answer's citations as claims and sources, for AskView.
// A claim is the words before a group of [n] marks, back to its sentence's start; a source is the
// passages of one document page (several passages of the same page are one source to the reader).
// The quote shown for a claim is the sentence of its passage that shares most words with it.

const GROUP = /(?:[ \t]*\[(?:\d+|F)\])+/g
const BOUNDARY = /[.;:!?]\s+|\n+/g

// [{ text } | { text, refs }], refs the passage numbers (and "F") in the order written.
export function claims(text, n) {
  const out = []
  const clean = text.replace(/\*\*/g, '')
  let last = 0
  for (const m of clean.matchAll(GROUP)) {
    const before = clean.slice(last, m.index)
    const b = [...before.matchAll(BOUNDARY)].pop()
    const cut = b ? b.index + b[0].length : 0
    const lead = before.slice(cut).match(/^\s*(?:[-*•]\s+|\d+[.)]\s+)?/)[0].length
    const refs = []
    for (const r of m[0].matchAll(/\[(\d+|F)\]/g)) {
      const v = r[1] === 'F' ? 'F' : Number(r[1])
      if (!refs.includes(v) && (v === 'F' || (v >= 1 && v <= n))) refs.push(v)
    }
    if (cut + lead) out.push({ text: before.slice(0, cut + lead) })
    out.push(refs.length ? { text: before.slice(cut + lead), refs } : { text: before.slice(cut + lead) })
    last = m.index + m[0].length
  }
  const tail = clean.slice(last).replace(/\[(?:\d*|F?)$/, '')   // a mark still being written
  if (tail) out.push({ text: tail })
  return out
}

// The sources the answer cites, in order of first use: { key, nums, passage, num } (passage null for "F").
export function sources(parts, passages) {
  const out = []
  const byKey = new Map()
  for (const p of parts) {
    for (const r of p.refs || []) {
      const ps = r === 'F' ? null : passages[r - 1]
      const key = r === 'F' ? 'F' : `${ps.doc_sha256}|${ps.page_from ?? ''}`
      let s = byKey.get(key)
      if (!s) {
        s = { key, nums: [], passage: ps, num: out.length + 1 }
        byKey.set(key, s)
        out.push(s)
      }
      if (!s.nums.includes(r)) s.nums.push(r)
    }
  }
  return out
}

export const sourceOf = (srcs, r) => srcs.find((s) => s.nums.includes(r))

const norm = (s) => s.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
const terms = (s) => norm(s).split(/[^\p{L}\p{N}.,%€]+/u).map((w) => w.replace(/^[.,]+|[.,]+$/g, ''))
  .filter((w) => w.length >= 4 || /\d/.test(w))

// The sentence of `passage` closest to `claim`, at most `max` characters, with where it starts.
export function excerpt(passage, claim, max = 240) {
  const text = passage.replace(/[ \t]+/g, ' ')
  const want = new Set(terms(claim))
  const sents = []
  let start = 0
  for (const m of text.matchAll(/(?<=[.;:])\s+|\n+/g)) {
    sents.push([start, m.index])
    start = m.index + m[0].length
  }
  sents.push([start, text.length])
  let best = sents[0], bestScore = -1
  for (const [a, b] of sents) {
    const s = text.slice(a, b).trim()
    if (s.length < 12) continue
    const score = terms(s).reduce((k, w) => k + (want.has(w) ? (/\d/.test(w) ? 3 : 1) : 0), 0)
    if (score > bestScore) { best = [a, b]; bestScore = score }
  }
  let [a, b] = best
  const raw = text.slice(a, b).trim()
  const cut = raw.length > max ? raw.slice(0, raw.lastIndexOf(' ', max) > 0 ? raw.lastIndexOf(' ', max) : max) : raw
  return { at: a, text: `${a > 0 ? '…' : ''}${cut.replace(/[.;:,]$/, '')}${cut.length < raw.length || b < text.length ? '…' : ''}` }
}
