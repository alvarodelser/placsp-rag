import React, { useState, useEffect } from 'react'
import { getPliegos, triggerPliegosAnalysis } from '../api.js'

export default function PliegosModal({ syndicationId, title, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('executive')

  useEffect(() => {
    let active = true
    setLoading(true)
    getPliegos(syndicationId)
      .then((res) => {
        if (!active) return
        setData(res)
        setLoading(false)
      })
      .catch((err) => {
        if (!active) return
        setError(err.message)
        setLoading(false)
      })
    return () => { active = false }
  }, [syndicationId])

  const handleTriggerAnalysis = async () => {
    try {
      await triggerPliegosAnalysis(syndicationId)
      alert("El análisis profundo se está generando en segundo plano. Esto puede tardar varios minutos (OCR + IA). Vuelve más tarde.")
    } catch (err) {
      alert("Error al iniciar el análisis: " + err.message)
    }
  }

  // Click outside to close
  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div className="pliegos-modal-backdrop" onClick={handleBackdrop}>
      <div className="pliegos-modal">
        <div className="modal-header">
          <h2>Análisis Inteligente de Pliegos</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        <div className="modal-subtitle">
          {title}
        </div>

        {loading && <div className="modal-body"><div className="loader">Analizando...</div></div>}
        {error && <div className="modal-body error">Error: {error}</div>}
        
        {!loading && !error && !data && (
          <div className="modal-body">
            <p>El análisis inteligente aún no está disponible para esta licitación.</p>
          </div>
        )}

        {!loading && !error && data && (
          <div className="modal-body">
            <div className="tabs">
              <button 
                className={activeTab === 'executive' ? 'active' : ''} 
                onClick={() => setActiveTab('executive')}>
                Resumen Ejecutivo
              </button>
              <button 
                className={activeTab === 'criteria' ? 'active' : ''} 
                onClick={() => setActiveTab('criteria')}>
                Criterios y Estrategia
              </button>
              <button 
                className={activeTab === 'risks' ? 'active' : ''} 
                onClick={() => setActiveTab('risks')}>
                Riesgos Legales
              </button>
            </div>

            <div className="tab-content">
              {activeTab === 'executive' && (
                <div className="tab-pane">
                  <h3>Resumen Ejecutivo (AI)</h3>
                  {data.executive_summary_json ? (
                    <div className="ai-content">
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {data.executive_summary_json}
                      </pre>
                    </div>
                  ) : (
                    <div>
                      <p>El análisis ejecutivo (Tier 2) aún no se ha generado para esta licitación.</p>
                      <button className="trigger-btn" onClick={handleTriggerAnalysis}>
                        Generar Análisis Completo (OCR + IA)
                      </button>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'criteria' && (
                <div className="tab-pane">
                  <h3>Estrategia de Puntuación</h3>
                  {data.scoring_strategy_json ? (
                    <div className="ai-content" style={{ marginBottom: '20px' }}>
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {data.scoring_strategy_json}
                      </pre>
                    </div>
                  ) : (
                    <p style={{ color: '#718096', fontStyle: 'italic', marginBottom: '20px' }}>
                      Estrategia AI no generada aún.
                    </p>
                  )}
                  
                  <h3>Criterios de Adjudicación (Extraídos de la Plataforma)</h3>
                  {data.criteria && data.criteria.criterios_adjudicacion ? (
                    <ul className="criteria-list">
                      {data.criteria.criterios_adjudicacion.map((c, i) => (
                        <li key={i}>
                          <strong>{c.nombre}</strong>
                          {c.ponderacion && <span className="badge weight">{c.ponderacion} pts</span>}
                          {c.subtipo && <div className="subtext">{c.subtipo}</div>}
                        </li>
                      ))}
                    </ul>
                  ) : <p>No se encontraron criterios estructurados.</p>}
                  
                  {data.criteria && data.criteria.garantia_definitiva_pct && (
                    <div className="box">
                      <h4>Garantía Definitiva</h4>
                      <p>{data.criteria.garantia_definitiva_pct}%</p>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'risks' && (
                <div className="tab-pane">
                  <h3>Análisis de Riesgos Legales (PCAP)</h3>
                  {data.risk_analysis_json ? (
                    <div className="ai-content">
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {data.risk_analysis_json}
                      </pre>
                      
                      <h4 style={{ marginTop: '24px' }}>Datos Extraídos</h4>
                      <pre style={{ background: '#f4f4f4', padding: '10px', overflowX: 'auto', fontSize: '0.85rem' }}>
                        {data.pcap_analysis_json}
                      </pre>
                    </div>
                  ) : (
                    <div>
                      <p>Este análisis requiere descargar y procesar el PDF del Pliego de Cláusulas Administrativas usando IA profunda.</p>
                      <button className="trigger-btn" onClick={handleTriggerAnalysis}>
                        Generar Análisis Completo (OCR + IA)
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
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
        .tabs { display: flex; border-bottom: 1px solid #e2e8f0; margin-bottom: 16px; }
        .tabs button {
          padding: 8px 16px; border: none; background: none; cursor: pointer;
          font-weight: 500; color: #718096; border-bottom: 2px solid transparent;
        }
        .tabs button.active { color: #3182ce; border-bottom-color: #3182ce; }
        .tabs button:hover { color: #2b6cb0; }
        .tab-pane h3 { margin-top: 0; font-size: 1.1rem; }
        .criteria-list { list-style: none; padding: 0; }
        .criteria-list li {
          padding: 12px; border: 1px solid #e2e8f0; border-radius: 6px; margin-bottom: 8px;
          display: flex; flex-direction: column; gap: 4px;
        }
        .badge.weight { background: #ebf8ff; color: #2b6cb0; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; align-self: flex-start;}
        .subtext { font-size: 0.85rem; color: #718096; }
        .box { padding: 12px; background: #f7fafc; border-radius: 6px; margin-top: 16px; }
        .box h4 { margin: 0 0 4px 0; font-size: 0.95rem; }
        .trigger-btn { background: #3182ce; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; margin-top: 12px; }
        .trigger-btn:hover { background: #2b6cb0; }
        .ai-content { background: #f0fff4; border: 1px solid #c6f6d5; border-radius: 6px; padding: 16px; }
      `}</style>
    </div>
  )
}
