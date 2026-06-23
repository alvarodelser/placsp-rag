import { useMemo, useState } from 'react'
import cpvMap from '../codelists/cpv.json'
import { cpvLevel, cpvPath, cpvChildren } from '../cpv.js'

const ENTRIES = Object.entries(cpvMap) // [code, label][]

export default function CpvSelect({ value, onChange }) {
  const [term, setTerm] = useState('')
  const [expanded, setExpanded] = useState(null)

  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.startsWith(t) || label.toLowerCase().includes(t)) {
        out.push([code, label])
        if (out.length >= 50) break
      }
    }
    return out
  }, [term])

  function add(code) {
    if (!value.includes(code)) onChange([...value, code])
    setTerm('')
  }
  function remove(code) {
    onChange(value.filter((c) => c !== code))
  }

  return (
    <div className="cpv-select">
      <input
        type="search"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="CPV: código o descripción (p. ej. limpieza)"
      />
      {matches.length > 0 && (
        <ul className="cpv-suggestions">
          {matches.map(([code, label]) => (
            <li key={code} onClick={() => add(code)}>
              <span className="cpv-code">{code}</span> · {label}
              {cpvPath(code, cpvMap).length > 0 && (
                <div className="cpv-path">{cpvPath(code, cpvMap).join(' › ')}</div>
              )}
            </li>
          ))}
        </ul>
      )}
      {value.length > 0 && (
        <div className="cpv-chips">
          {value.map((code) => {
            const kids = cpvChildren(code, cpvMap)
            const open = expanded === code
            return (
              <div className="cpv-chip-wrap" key={code}>
                <span className="chip">
                  {code} · {cpvMap[code] || '—'}
                  {cpvLevel(code) < 8 && <em className="hint"> (incluye sub-códigos)</em>}
                  {kids.length > 0 && (
                    <button type="button" className="drill" aria-label="Subcódigos"
                      onClick={() => setExpanded(open ? null : code)}>{open ? '▾' : '▸'}</button>
                  )}
                  <button type="button" onClick={() => remove(code)} aria-label="Quitar">✕</button>
                </span>
                {open && kids.length > 0 && (
                  <ul className="cpv-subcodes">
                    {kids.map((kc) => (
                      <li key={kc} onClick={() => { onChange(value.map((c) => (c === code ? kc : c))); setExpanded(kc) }}>
                        <span className="cpv-code">{kc}</span> · {cpvMap[kc] || '—'}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
