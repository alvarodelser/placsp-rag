// search-ui/src/pilot/ui.jsx — the pilot's small shared pieces, so the same thing looks the same on
// every page: loading and errors, a tender's state, where a passage comes from, tabs, links out.
import { tenderState, roleEs } from './labels.js'
import { LoaderCircle, ArrowUpRight } from '../icons.js'

export function Loading({ size = 22 }) {
  return <div className="loading-state"><LoaderCircle size={size} className="spinner" /></div>
}

export function ErrorNote({ children }) {
  return <div className="err">{children}</div>
}

// A tender's state as a coloured dot and a word; the feed's raw status on hover.
export function StatusBadge({ t, label }) {
  const s = label ? { cls: 'st-done', es: label } : tenderState(t)
  if (!s) return null
  return <span className={`status ${s.cls}`} title={t?.status || undefined}>{s.es}</span>
}

// Where a passage comes from — its document's role, number and page — drawn the same wherever a
// source is named: hover cards, the provenance window, the answer's citations, the panels.
export function SourceRef({ role, seq, page, pageTo, num, className = '', title }) {
  const pages = page ? `pág. ${page}${pageTo && pageTo !== page ? `–${pageTo}` : ''}` : null
  return (
    <span className={`src ${className}`} title={title}>
      {num != null && <span className="src-num">{num}</span>}
      <b>{role ? roleEs(role) : 'PLACSP'}</b>
      {seq != null && <span>doc {seq}</span>}
      {pages && <span>{pages}</span>}
    </span>
  )
}
// The same as a string, for places only text can go (a frame's tag drawn by CSS).
export const sourceText = (role, seq, page) =>
  [roleEs(role), seq != null ? `doc ${seq}` : null, page ? `pág. ${page}` : null].filter(Boolean).join(' · ')

// Underlined tabs: `items` is [key, label]; anything after them (a link out) goes in `extra`.
export function Tabs({ items, value, onChange, extra, className = '' }) {
  return (
    <nav className={`tabs ${className}`} role="tablist">
      {items.map(([k, label]) => (
        <button key={k} type="button" role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>{label}</button>
      ))}
      {extra && <span className="tabs-extra">{extra}</span>}
    </nav>
  )
}

// A link out of the pilot (the Plataforma, an original): always with the same arrow.
export function ExtLink({ href, children, className = '' }) {
  if (!href) return null
  return <a className={`ext ${className}`} href={href} target="_blank" rel="noreferrer">{children} <ArrowUpRight size={13} className="ico" /></a>
}
