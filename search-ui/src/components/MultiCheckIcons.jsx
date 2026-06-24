/**
 * MultiCheckIcons — like MultiCheck but with icons and optional contract-count badges.
 * Used for Resultado, Tipo de contrato, and Procedimiento filters.
 */

function fmt(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`
  return String(n)
}

export default function MultiCheckIcons({ map, value, onChange, icons = {}, counts = {} }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }
  return (
    <div className="mci-grid">
      {Object.entries(map).map(([code, name]) => {
        const active = value.includes(code)
        const Icon = icons[code]
        const n = counts[code]
        return (
          <button
            key={code}
            type="button"
            className={`mci-card${active ? ' on' : ''}`}
            onClick={() => toggle(code)}
            aria-pressed={active}
          >
            {Icon && (
              <span className="mci-icon">
                <Icon size={18} weight={active ? 'fill' : 'regular'} />
              </span>
            )}
            <span className="mci-label">{name}</span>
            {n != null && (
              <span className="mci-count">{fmt(n)}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}
