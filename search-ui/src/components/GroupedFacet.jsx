/**
 * GroupedFacet — a flat grid of grouped facet cards. Used for Resultado and
 * Tipo, where each card stands for a set of granular codes. Clicking toggles
 * the whole set (via toggleGroup); the count is the summed group count.
 */
import GroupCard from './GroupCard.jsx'

export default function GroupedFacet({ groups, value = [], counts = {}, onChange }) {
  return (
    <div className="mci-grid">
      {groups.map((g) => (
        <GroupCard key={g.key} group={g} value={value} counts={counts} onChange={onChange} />
      ))}
    </div>
  )
}
