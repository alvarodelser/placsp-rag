/**
 * GroupedFacet — a flat grid of grouped facet cards. Used for Resultado and
 * Tipo, where each card stands for a set of granular codes. Clicking toggles
 * the whole set (via toggleGroup); the count is the summed group count.
 */
import FacetCard from './FacetCard.jsx'
import { groupActive, groupCount, toggleGroup } from '../facetGroups.js'

export default function GroupedFacet({ groups, value = [], counts = {}, onChange }) {
  return (
    <div className="mci-grid">
      {groups.map((g) => (
        <FacetCard
          key={g.key}
          label={g.label}
          Icon={g.Icon}
          color={g.color}
          active={groupActive(g, value)}
          count={groupCount(g, counts)}
          onToggle={() => onChange(toggleGroup(g, value))}
        />
      ))}
    </div>
  )
}
