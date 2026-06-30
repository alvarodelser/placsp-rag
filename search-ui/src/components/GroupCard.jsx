/**
 * GroupCard — a grouped facet card plus an optional disclosure caret that
 * reveals the granular sub-codes it folds together. The card toggles the whole
 * group; each sub-option toggles a single code. Used by GroupedFacet and
 * ProcedureAxis.
 */
import { useState } from 'react'
import FacetCard from './FacetCard.jsx'
import { CaretDown } from '../icons.js'
import { groupActive, groupCount, toggleGroup, toggleCode } from '../facetGroups.js'

function fmt(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`
  return String(n)
}

export default function GroupCard({ group, value = [], counts = {}, onChange }) {
  const [open, setOpen] = useState(false)
  const v = value || []
  const selected = group.codes.filter((c) => v.includes(c)).length
  const partial = selected > 0 && selected < group.codes.length
  const expandable = group.options.length > 1

  return (
    <div className="gc">
      <div className="gc-row">
        <FacetCard
          label={group.label}
          Icon={group.Icon}
          color={group.color}
          active={groupActive(group, v)}
          partial={partial}
          count={groupCount(group, counts)}
          onToggle={() => onChange(toggleGroup(group, v))}
        />
        {expandable && (
          <button
            type="button"
            className={`gc-caret${open ? ' open' : ''}`}
            aria-label={`Mostrar opciones de ${group.label}`}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <CaretDown size={14} weight="bold" />
          </button>
        )}
      </div>
      {open && expandable && (
        <ul className="gc-subs">
          {group.options.map((o) => {
            const on = v.includes(o.code)
            const n = counts?.[o.code]
            return (
              <li key={o.code}>
                <button
                  type="button"
                  className={`gc-sub${on ? ' on' : ''}`}
                  aria-pressed={on}
                  onClick={() => onChange(toggleCode(o.code, v))}
                >
                  <span className="gc-sub-label">{o.label}</span>
                  {n != null && <span className="mci-count">{fmt(n)}</span>}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
