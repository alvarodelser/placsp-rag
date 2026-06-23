import { useMemo, useState } from 'react'
import nutsMap from '../codelists/nuts.json'

const ENTRIES = Object.entries(nutsMap) // [code, label][]

// NUTS codes are hierarchical by prefix: country(2) > NUTS1(3) > NUTS2(4) >
// NUTS3(5). The API prefix-matches, so selecting "ES3" matches every ES3*.
// A code shorter than 5 chars therefore stands for a whole sub-region.
export default function NutsSelect({ value, onChange }) {
  const [term, setTerm] = useState('')

  const matches = useMemo(() => {
    const t = term.trim().toLowerCase()
    if (t.length < 2) return []
    const out = []
    for (const [code, label] of ENTRIES) {
      if (code.toLowerCase().startsWith(t) || label.toLowerCase().includes(t)) {
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
        placeholder="NUTS: código o zona (p. ej. Madrid)"
      />
      {matches.length > 0 && (
        <ul className="cpv-suggestions">
          {matches.map(([code, label]) => (
            <li key={code} onClick={() => add(code)}>
              <span className="cpv-code">{code}</span> · {label}
            </li>
          ))}
        </ul>
      )}
      {value.length > 0 && (
        <div className="chips">
          {value.map((code) => (
            <span className="chip" key={code}>
              {code} · {nutsMap[code] || '—'}
              {code.length < 5 && <em className="hint"> (incluye sub-zonas)</em>}
              <button type="button" onClick={() => remove(code)} aria-label="Quitar">✕</button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
