/**
 * FacetCard — a single toggleable facet card (icon + label + optional count).
 * Shared by GroupedFacet (Resultado, Tipo) and ProcedureAxis (Procedimiento).
 * `color` adds a semantic class (e.g. green/gray/red) consumed by styles.css.
 */

function fmt(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`
  return String(n)
}

export default function FacetCard({ label, Icon, active, partial, count, color, onToggle }) {
  const label_n = fmt(count)
  return (
    <button
      type="button"
      className={`mci-card${active ? ' on' : ''}${partial ? ' mci-partial' : ''}${color ? ` mci-${color}` : ''}`}
      onClick={onToggle}
      aria-pressed={active}
    >
      {Icon && (
        <span className="mci-icon">
          <Icon size={18} weight={active ? 'fill' : 'regular'} />
        </span>
      )}
      <span className="mci-label">{label}</span>
      {label_n != null && <span className="mci-count">{label_n}</span>}
    </button>
  )
}
