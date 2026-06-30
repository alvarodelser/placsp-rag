import { useMemo, useState } from 'react'
import cpvMap from '../codelists/cpv.json'
import { cpvChildren, cpvLevel } from '../cpv.js'
import { MagnifyingGlass, CaretRight, X } from '../icons.js'

const ENTRIES = Object.entries(cpvMap)

function cpvShort(code) {
  const base = code.split('-')[0].replace(/0+$/, '')
  return base + '_'
}

function topLevel() {
  return Object.keys(cpvMap).filter(c => cpvLevel(c) === 2).sort()
}

export default function CpvMiller({ value, onChange, filterParams = {} }) {
  const [midPath, setMidPath] = useState([])
  const [midSelected, setMidSelected] = useState(null)
  const [term, setTerm] = useState('')

  const midItems = useMemo(() => {
    if (midPath.length === 0) return topLevel()
    return cpvChildren(midPath[midPath.length - 1], cpvMap)
  }, [midPath])

  const rightItems = useMemo(() => {
    if (!midSelected) return []
    return cpvChildren(midSelected, cpvMap)
  }, [midSelected])

  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.startsWith(t) || label.toLowerCase().includes(t)) out.push(code)
      if (out.length >= 40) break
    }
    return out
  }, [term])

  const add = (code) => { if (!value.includes(code)) onChange([...value, code]) }
  const remove = (code) => onChange(value.filter(c => c !== code))

  const navigateTo = (depth) => {
    setMidPath(prev => prev.slice(0, depth))
    setMidSelected(null)
  }

  const clickMid = (code) => {
    const kids = cpvChildren(code, cpvMap)
    if (kids.length > 0) {
      setMidSelected(prev => prev === code ? null : code)
    } else {
      add(code)
    }
  }

  const clickRight = (code) => {
    const kids = cpvChildren(code, cpvMap)
    if (kids.length > 0) {
      setMidPath(prev => [...prev, midSelected])
      setMidSelected(code)
      setTerm('')
    } else {
      add(code)
    }
  }

  const browseItems = term.length >= 2 ? matches : midItems
  const isSearching = term.length >= 2

  return (
    <div className="cpv-miller">
      <div className="cm-search">
        <MagnifyingGlass size={16} />
        <input type="search" value={term} onChange={e => setTerm(e.target.value)}
          placeholder="Buscar CPV: código o descripción" />
      </div>

      <div className="cm-three">
        {/* Left: added codes */}
        <div className="cm-pane cm-added">
          <div className="cm-pane-title">Añadidos{value.length > 0 ? ` (${value.length})` : ''}</div>
          {value.length === 0
            ? <div className="cm-empty">Ninguno</div>
            : value.map(code => (
              <div key={code} className="cm-item">
                <span className="cm-short">{cpvShort(code)}</span>
                <span className="cm-label">{cpvMap[code] || '—'}</span>
                <button type="button" className="cm-remove" aria-label="Quitar" onClick={() => remove(code)}>
                  <X size={11} />
                </button>
              </div>
            ))
          }
        </div>

        {/* Middle: browse / search */}
        <div className="cm-pane cm-browse">
          {!isSearching && midPath.length > 0 && (
            <div className="cm-breadcrumb">
              <span className="cm-bc-link" onClick={() => navigateTo(0)}>Inicio</span>
              {midPath.map((code, i) => (
                <span key={code}>
                  <span className="cm-bc-sep">›</span>
                  <span className="cm-bc-link" onClick={() => navigateTo(i + 1)}>{cpvShort(code)}</span>
                </span>
              ))}
            </div>
          )}
          {browseItems.map(code => {
            const hasKids = cpvChildren(code, cpvMap).length > 0
            return (
              <div key={code}
                className={`cm-item${midSelected === code && !isSearching ? ' cm-active' : ''}`}
                onClick={() => clickMid(code)}>
                <span className="cm-short">{cpvShort(code)}</span>
                <span className="cm-label">{cpvMap[code] || '—'}</span>
                {hasKids
                  ? <CaretRight size={12} className="cm-caret" />
                  : <button type="button" className="cm-add-btn" aria-label="Añadir"
                      onClick={e => { e.stopPropagation(); add(code) }}>+</button>
                }
              </div>
            )
          })}
        </div>

        {/* Right: children of selected middle item */}
        <div className="cm-pane cm-children">
          {midSelected && !isSearching ? (
            <>
              <div className="cm-pane-title">
                <span className="cm-short">{cpvShort(midSelected)}</span> {cpvMap[midSelected]}
              </div>
              {rightItems.length === 0
                ? <div className="cm-empty">Sin subcódigos</div>
                : rightItems.map(code => {
                  const hasKids = cpvChildren(code, cpvMap).length > 0
                  const parentLen = cpvLevel(midSelected)
                  const base = code.split('-')[0].replace(/0+$/, '')
                  const newPart = base.slice(parentLen)
                  return (
                    <div key={code} className="cm-item" onClick={() => clickRight(code)}>
                      <span className="cm-short cm-short-dim">{cpvShort(midSelected).slice(0, -1)}</span>
                      <span className="cm-short">{newPart}_</span>
                      <span className="cm-label">{cpvMap[code] || '—'}</span>
                      {hasKids && <CaretRight size={12} className="cm-caret" />}
                    </div>
                  )
                })
              }
            </>
          ) : (
            <div className="cm-empty cm-empty-hint">Selecciona una categoría</div>
          )}
        </div>
      </div>
    </div>
  )
}
