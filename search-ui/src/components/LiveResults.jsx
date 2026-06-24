export default function LiveResults({ total, results = [], loading = false }) {
  return (
    <aside className="live-results">
      <div className={`lr-count${loading ? ' loading' : ''}`}>
        {total != null ? total.toLocaleString('es-ES') : '—'} <span>resultados</span>
      </div>
      <div className="lr-list">
        {results.slice(0, 8).map((r) => (
          <div className="lr-item" key={r._id || r.syndication_id}>
            <div className="lr-title">{r.title || r.expediente || 'Sin título'}</div>
            {r.contracting_authority && <div className="lr-auth">{r.contracting_authority}</div>}
          </div>
        ))}
      </div>
    </aside>
  )
}
