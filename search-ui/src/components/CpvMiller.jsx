import { useMemo, useState, useEffect, useRef } from 'react'
import cpvMap from '../codelists/cpv.json'
import { columns } from '../miller.js'
import { cpvPath } from '../cpv.js'
import { MagnifyingGlass, CaretRight, X } from '../icons.js'
import { cpvDist } from '../api.js'

const ENTRIES = Object.entries(cpvMap)

function useCpvCounts(activeCodes, filterParams) {
  const [counts, setCounts] = useState({})
  const cacheRef = useRef({})
  const key = activeCodes.join(',') + '|' + JSON.stringify(filterParams)
  useEffect(() => {
    if (!activeCodes.length) return
    if (cacheRef.current[key]) { setCounts(cacheRef.current[key]); return }
    let cancelled = false
    cpvDist({ ...filterParams, codes: activeCodes })
      .then(d => { if (!cancelled) { cacheRef.current[key] = d; setCounts(d) } })
      .catch(() => {})
    return () => { cancelled = true }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return counts
}

export default function CpvMiller({ value, onChange, filterParams = {} }) {
  const [path, setPath] = useState([])
  const [term, setTerm] = useState('')

  const cols = useMemo(() => columns(path, cpvMap), [path])
  const activeCodes = useMemo(
    () => (cols[cols.length - 1]?.items || []).map(i => i.code),
    [cols]
  )
  const counts = useCpvCounts(activeCodes, filterParams)
  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.startsWith(t) || label.toLowerCase().includes(t)) out.push([code, label])
      if (out.length >= 40) break
    }
    return out
  }, [term])

  const add = (code) => { if (!value.includes(code)) onChange([...value, code]); setTerm('') }
  const remove = (code) => onChange(value.filter((c) => c !== code))
  const drill = (depth, code) => setPath([...path.slice(0, depth), code])

  return (
    <div className="cpv-miller">
      <div className="cm-search">
        <MagnifyingGlass size={16} />
        <input type="search" value={term} onChange={(e) => setTerm(e.target.value)}
          placeholder="Buscar CPV: código o descripción" />
      </div>
      {matches.length > 0 ? (
        <ul className="cm-matches">
          {matches.map(([code, label]) => (
            <li key={code} onClick={() => add(code)}>
              <span className="cpv-code">{code}</span> · {label}
              {cpvPath(code, cpvMap).length > 0 && (
                <div className="cpv-path">{cpvPath(code, cpvMap).join(' › ')}</div>)}
            </li>
          ))}
        </ul>
      ) : (
        <div className="cm-cols">
          {cols.map((col, depth) => {
            const isActive = depth === cols.length - 1
            return (
              <div className="cm-col" key={depth}>
                {col.items.map(({ code, label }) => (
                  <div key={code}
                    className={`cm-item${col.activeCode === code ? ' path' : ''}`}
                    onClick={() => drill(depth, code)}>
                    <span className="cm-label"><span className="cpv-code">{code}</span> {label}</span>
                    {isActive && counts[code] != null && (
                      <span className="cm-count">{counts[code].toLocaleString('es-ES')}</span>
                    )}
                    <button type="button" className="cm-add" aria-label="Añadir"
                      onClick={(e) => { e.stopPropagation(); add(code) }}>+</button>
                    <CaretRight size={12} />
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
      {value.length > 0 && (
        <div className="cm-chips">
          {value.map((code) => (
            <span className="chip" key={code}>
              {code} · {cpvMap[code] || '—'}
              <button type="button" aria-label="Quitar" onClick={() => remove(code)}><X size={11} /></button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
