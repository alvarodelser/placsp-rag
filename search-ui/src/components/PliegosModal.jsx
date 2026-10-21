import React, { useState, useEffect } from 'react'
import { getPliegos } from '../api.js'

const pct = v => (v === null || v === undefined ? null : `${v}%`)
const money = v => (v === null || v === undefined ? null : `${Number(v).toLocaleString('es-ES')} €`)

function Section({ title, children }) {
  return <div className="box"><h4>{title}</h4>{children}</div>
}

export default function PliegosModal({ syndicationId, title, onClose }) {
  const [crit, setCrit] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    getPliegos(syndicationId)
      .then(d => { if (active) setCrit(d ? d.criteria : null) })
      .catch(e => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [syndicationId])

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose()
  }
  const c = crit || {}
  const solvency = [...(c.solvencia_economica || []), ...(c.solvencia_tecnica || [])]

  return (
    <div className="pliegos-modal-backdrop" onClick={handleBackdrop}>
      <div className="pliegos-modal">
        <div className="modal-header">
          <h2>Pliego: datos de la plataforma</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        <div className="modal-subtitle">{title}</div>

        {loading && <div className="modal-body"><div className="loader">Cargando...</div></div>}
        {error && <div className="modal-body error">Error: {error}</div>}
        {!loading && !error && !crit && (
          <div className="modal-body"><p>La plataforma no publica criterios ni pliegos para esta licitación.</p></div>
        )}

        {!loading && !error && crit && (
          <div className="modal-body">
            <Section title="Criterios de adjudicación">
              {c.criterios_adjudicacion && c.criterios_adjudicacion.length ? (
                <ul className="criteria-list">
                  {c.criterios_adjudicacion.map((x, i) => (
                    <li key={i}>
                      <strong>{x.nombre}</strong>
                      {x.ponderacion !== null && x.ponderacion !== undefined && <span className="badge weight">{x.ponderacion} pts</span>}
                      {(x.tipo || x.subtipo) && <div className="subtext">{[x.tipo, x.subtipo, x.lote && `lote ${x.lote}`].filter(Boolean).join(' · ')}</div>}
                      {x.nota && <div className="subtext">{x.nota}</div>}
                    </li>
                  ))}
                </ul>
              ) : <p>No publicados en la plataforma.</p>}
            </Section>

            {(c.garantia_provisional_pct || c.garantia_definitiva_pct || c.garantia_complementaria_pct) && (
              <Section title="Garantías">
                <ul>
                  {c.garantia_provisional_pct && <li>Provisional: {pct(c.garantia_provisional_pct)}</li>}
                  {c.garantia_definitiva_pct && <li>Definitiva: {pct(c.garantia_definitiva_pct)}</li>}
                  {c.garantia_complementaria_pct && <li>Complementaria: {pct(c.garantia_complementaria_pct)}</li>}
                </ul>
              </Section>
            )}

            {(solvency.length > 0 || (c.clasificacion_empresarial || []).length > 0 || c.num_empleados_min || c.anos_experiencia_min) && (
              <Section title="Solvencia y clasificación">
                <ul>
                  {(c.clasificacion_empresarial || []).map((x, i) => <li key={`c${i}`}>Clasificación: {x}</li>)}
                  {solvency.map((x, i) => (
                    <li key={`s${i}`}>{[x.tipo, x.descripcion, money(x.umbral)].filter(Boolean).join(' — ')}</li>
                  ))}
                  {c.num_empleados_min && <li>Plantilla mínima: {c.num_empleados_min}</li>}
                  {c.anos_experiencia_min && <li>Años de actividad mínimos: {c.anos_experiencia_min}</li>}
                </ul>
              </Section>
            )}

            {(c.plazo_ejecucion || c.subcontratacion || (c.condiciones_especiales || []).length > 0) && (
              <Section title="Ejecución">
                <ul>
                  {c.plazo_ejecucion && <li>Plazo: {c.plazo_ejecucion}</li>}
                  {c.subcontratacion && <li>Subcontratación: {c.subcontratacion}</li>}
                  {(c.condiciones_especiales || []).map((x, i) => <li key={i}>{x}</li>)}
                </ul>
              </Section>
            )}

            {(c.pdf_links || []).length > 0 && (
              <Section title="Documentos">
                <ul>
                  {c.pdf_links.map((d, i) => (
                    <li key={i}><a href={d.url} target="_blank" rel="noreferrer">{d.nombre}</a></li>
                  ))}
                </ul>
              </Section>
            )}
          </div>
        )}
      </div>

      <style>{`
        .pliegos-modal-backdrop {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          display: flex; align-items: center; justify-content: center;
          z-index: 1000;
        }
        .pliegos-modal {
          background: #fff; border-radius: 8px; width: 90%; max-width: 800px;
          max-height: 90vh; display: flex; flex-direction: column;
          box-shadow: 0 10px 25px rgba(0,0,0,0.2);
        }
        .modal-header {
          padding: 16px 24px; border-bottom: 1px solid #eee;
          display: flex; justify-content: space-between; align-items: center;
        }
        .modal-header h2 { margin: 0; font-size: 1.25rem; color: #2d3748; }
        .close-btn { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #718096; }
        .modal-subtitle { padding: 8px 24px; font-size: 0.9rem; color: #4a5568; background: #f7fafc; }
        .modal-body { padding: 24px; overflow-y: auto; }
        .criteria-list { list-style: none; padding: 0; }
        .criteria-list li {
          padding: 12px; border: 1px solid #e2e8f0; border-radius: 6px; margin-bottom: 8px;
          display: flex; flex-direction: column; gap: 4px;
        }
        .badge.weight { background: #ebf8ff; color: #2b6cb0; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; align-self: flex-start;}
        .subtext { font-size: 0.85rem; color: #718096; }
        .box { padding: 12px; background: #f7fafc; border-radius: 6px; margin-top: 16px; }
        .box:first-child { margin-top: 0; }
        .box ul { margin: 4px 0 0; padding-left: 18px; }
        .box h4 { margin: 0 0 4px 0; font-size: 0.95rem; }
      `}</style>
    </div>
  )
}
