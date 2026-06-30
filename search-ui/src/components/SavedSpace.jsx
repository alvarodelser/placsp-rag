import { useState, useEffect } from 'react'
import { listSaved } from '../api.js'
import { X, BookmarkSimple, CircleNotch } from '../icons.js'

export default function SavedSpace({ onClose, onRemove }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    listSaved({ offset: 0, limit: 100 })
      .then((data) => {
        setItems(data.items || [])
        setTotal(data.total || 0)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  function handleRemove(itemId) {
    // Optimistic removal from list
    setItems((prev) => prev.filter((i) => i.item_id !== itemId))
    setTotal((t) => Math.max(0, t - 1))
    onRemove?.(itemId)
  }

  return (
    <div className="saved-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="saved-panel">
        <div className="saved-head">
          <div className="saved-head-title">
            <BookmarkSimple size={20} weight="fill" />
            <span>Mi Espacio</span>
            {!loading && <span className="saved-count">{total}</span>}
          </div>
          <button type="button" className="ws-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="saved-list">
          {loading && (
            <div className="saved-loading">
              <CircleNotch size={28} className="spinner" />
              <span>Cargando…</span>
            </div>
          )}

          {error && <div className="err">{error}</div>}

          {!loading && !error && items.length === 0 && (
            <div className="saved-empty">
              <BookmarkSimple size={40} weight="light" />
              <p>No tienes licitaciones guardadas aún</p>
              <span>Pulsa «Guardar» en cualquier resultado para añadirlo aquí</span>
            </div>
          )}

          {!loading && items.map((item) => (
            <div className="saved-item" key={item.item_id}>
              <div className="saved-item-body">
                <div className="saved-title">
                  {item.source_url
                    ? <a href={item.source_url} target="_blank" rel="noopener noreferrer">{item.title || item.syndication_id || item.item_id}</a>
                    : (item.title || item.syndication_id || item.item_id)
                  }
                </div>
                <div className="saved-meta">
                  {item.syndication_id && <span className="saved-sid">{item.syndication_id}</span>}
                  {item.saved_at && (
                    <span className="saved-date">
                      Guardado {new Date(item.saved_at).toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                className="saved-remove"
                onClick={() => handleRemove(item.item_id)}
                title="Quitar de Mi Espacio"
              >
                Quitar
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
