/**
 * ProcedureAxis — Procedimiento facet laid out along a concurrence axis
 * (más concurrencia → más directo). On-axis groups render in order on a
 * gradient strip; off-axis groups (e.g. Otros) sit on a separate row below.
 */
import GroupCard from './GroupCard.jsx'

function Card({ group, value, counts, onChange }) {
  return <GroupCard group={group} value={value} counts={counts} onChange={onChange} />
}

export default function ProcedureAxis({ groups, value = [], counts = {}, onChange }) {
  const onAxis = groups.filter((g) => g.axis !== false)
  const offAxis = groups.filter((g) => g.axis === false)

  return (
    <div className="pa-wrap">
      <div className="pa-axis-hint">
        <span>más concurrencia</span>
        <span className="pa-axis-line" aria-hidden="true">◀──────────▶</span>
        <span>más directo</span>
      </div>
      <div className="pa-strip">
        {onAxis.map((g) => (
          <Card key={g.key} group={g} value={value} counts={counts} onChange={onChange} />
        ))}
      </div>
      {offAxis.length > 0 && (
        <div className="pa-offaxis">
          {offAxis.map((g) => (
            <Card key={g.key} group={g} value={value} counts={counts} onChange={onChange} />
          ))}
        </div>
      )}
    </div>
  )
}
