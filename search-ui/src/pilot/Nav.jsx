// search-ui/src/pilot/Nav.jsx — where the reader is and how to get back, under the search bar on
// every page but the start: "Atrás" (the page before in this visit, else one level up) and the
// trail from the start, each step named with its kind in the graph's colours (Expediente, Empresa,
// Órgano, Documento) and its short name; the last step is the page itself. Pages tell the trail
// their names with useNavName once they have loaded them.
import { createContext, useContext, useEffect } from 'react'
import { nodeInfo } from './labels.js'
import { go, previous, trail } from './route.js'
import { ArrowLeft, ChevronRight, House } from '../icons.js'

export const NavNames = createContext(() => {})

// `value`: {name} for a tender or a document, {name, label} for an organization.
export function useNavName(key, value) {
  const set = useContext(NavNames)
  const json = value ? JSON.stringify(value) : null
  useEffect(() => { if (key && json) set(key, JSON.parse(json)) }, [key, json, set])
}

const KIND = { Tender: 'Expediente', Company: 'Empresa', Authority: 'Órgano', Organization: 'Organización', Document: 'Documento' }
const label = (s) => (s.label && s.label !== 'Home' ? KIND[s.label] : null)
const text = (s) => [s.name, label(s)].filter(Boolean).join(' · ')

// The page's words for the browser's tab and for "Atrás"'s hint: a tab of a tender says whose.
export function pageTitle(steps) {
  if (steps.length < 2) return 'Inicio'
  const last = steps[steps.length - 1]
  return last.label ? text(last) : `${last.name} · ${steps[steps.length - 2].name}`
}

// What each page seen in this visit was called, for "Atrás"'s hint.
const titles = {}

// Mounted on every page (it draws nothing on the start) so the window's title follows the reader.
export default function Nav({ hash, route, names }) {
  const steps = trail(route, names)
  const title = pageTitle(steps)
  titles[hash] = title
  useEffect(() => { document.title = steps.length < 2 ? 'PLACSP · Piloto documental' : `${title} — PLACSP Piloto` }, [title, steps.length])
  if (steps.length < 2) return null
  const before = previous()
  const up = steps[steps.length - 2]
  const back = () => (before ? window.history.back() : go(up.to))
  const hint = before ? titles[before] : pageTitle(steps.slice(0, -1))

  return (
    <nav className="pnav" aria-label="Navegación">
      <button type="button" className="pnav-back" onClick={back} title={hint ? `Volver a ${hint}` : 'Volver'}>
        <ArrowLeft size={15} /> Atrás
      </button>
      <ol className="crumbs">
        {steps.map((s, i) => {
          const last = i === steps.length - 1
          const k = label(s)
          const body = <>
            {s.label === 'Home' ? <House size={14} aria-hidden="true" /> : null}
            {k && <span className="crumb-kind"><i style={{ background: nodeInfo(s.label).color }} />{k}</span>}
            <span className="crumb-name">{s.name}</span>
          </>
          return (
            <li key={i} className={last ? 'on' : ''}>
              {i > 0 && <ChevronRight size={14} className="crumb-sep" aria-hidden="true" />}
              {last ? <span className="crumb" aria-current="page" title={s.name}>{body}</span>
                : <a className="crumb" href={`#/pilot${s.to}`} title={s.name}>{body}</a>}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
