import { useMemo, useState, useEffect, useRef } from 'react'
import cpvMap from '../codelists/cpv.json'
import { cpvChildren, cpvLevel } from '../cpv.js'
import { MagnifyingGlass, CaretRight, X } from '../icons.js'
import { cpvDist } from '../api.js'

const ENTRIES = Object.entries(cpvMap)

function shortBase(code) {
  return code.split('-')[0].replace(/0+$/, '')
}

function ShortCode({ code }) {
  return (
    <span className="cm-short">
      {shortBase(code)}<span className="cm-cursor" />
    </span>
  )
}

function topLevel() {
  return Object.keys(cpvMap).filter(c => cpvLevel(c) === 2).sort()
}

function useCpvCounts(codes, filterParams) {
  const [counts, setCounts] = useState({})
  const cacheRef = useRef({})
  const key = [...codes].sort().join(',') + '|' + JSON.stringify(filterParams)
  useEffect(() => {
    if (!codes.length) return
    if (cacheRef.current[key]) { setCounts(cacheRef.current[key]); return }
    let cancelled = false
    cpvDist({ ...filterParams, codes })
      .then(d => { if (!cancelled) { cacheRef.current[key] = d; setCounts(d) } })
      .catch(() => {})
    return () => { cancelled = true }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return counts
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

  const visibleCodes = useMemo(
    () => [...midItems, ...rightItems],
    [midItems, rightItems]
  )
  const counts = useCpvCounts(visibleCodes, filterParams)

  const add = (code) => { if (!value.includes(code)) onChange([...value, code]) }
  const remove = (code) => onChange(value.filter(c => c !== code))
  const isSearching = term.length >= 2

  const navigateTo = (depth) => {
    setMidPath(prev => prev.slice(0, depth))
    setMidSelected(null)
  }

  const goBack = () => {
    setMidPath(prev => prev.slice(0, -1))
    setMidSelected(null)
  }

  const clickMid = (code) => {
    const kids = cpvChildren(code, cpvMap)
    if (kids.length === 0) {
      add(code)
    } else {
      setMidSelected(prev => prev === code ? null : code)
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

  const browseItems = isSearching ? matches : midItems

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
                <ShortCode code={code} />
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
              <button type="button" className="cm-back-btn" onClick={goBack}>← Atrás</button>
              <span className="cm-bc-link" onClick={() => navigateTo(0)}>Inicio</span>
              {midPath.map((code, i) => (
                <span key={code}>
                  <span className="cm-bc-sep">›</span>
                  <span className="cm-bc-link" onClick={() => navigateTo(i + 1)}>
                    {shortBase(code)}_
                  </span>
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
                <ShortCode code={code} />
                <span className="cm-label">{cpvMap[code] || '—'}</span>
                {counts[code] != null && (
                  <span className="cm-count-pill">{counts[code].toLocaleString('es-ES')}</span>
                )}
                <button type="button" className="cm-add-btn" aria-label="Añadir"
                  onClick={e => { e.stopPropagation(); add(code) }}>+</button>
                {hasKids && <CaretRight size={12} className="cm-caret" />}
              </div>
            )
          })}
        </div>

        {/* Right: children of selected middle item */}
        <div className="cm-pane cm-children">
          {midSelected && !isSearching ? (
            <>
              <div className="cm-pane-title">
                <ShortCode code={midSelected} />&nbsp;{cpvMap[midSelected]}
              </div>
              {rightItems.length === 0
                ? <div className="cm-empty">Sin subcódigos</div>
                : rightItems.map(code => {
                  const hasKids = cpvChildren(code, cpvMap).length > 0
                  return (
                    <div key={code} className="cm-item" onClick={() => clickRight(code)}>
                      <ShortCode code={code} />
                      <span className="cm-label">{cpvMap[code] || '—'}</span>
                      {counts[code] != null && (
                        <span className="cm-count-pill">{counts[code].toLocaleString('es-ES')}</span>
                      )}
                      <button type="button" className="cm-add-btn" aria-label="Añadir"
                        onClick={e => { e.stopPropagation(); add(code) }}>+</button>
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
