export default function FilterRail({ tabs, counts, openTab, onOpen }) {
  return (
    <nav className="filter-rail">
      {tabs.map(({ id, label }) => (
        <button type="button" key={id}
          className={`rail-tab${openTab === id ? ' active' : ''}`}
          onClick={() => onOpen(openTab === id ? null : id)}>
          {label}
          {counts[id] > 0 && <span className="rail-badge">{counts[id]}</span>}
        </button>
      ))}
    </nav>
  )
}
