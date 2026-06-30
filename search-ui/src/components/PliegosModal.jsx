import React, { useState, useEffect } from 'react'
import { getPliegos, getSavedAnalysis } from '../api.js'

export default function PliegosModal({ syndicationId, itemId, title, onClose }) {
  const [data, setData] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('executive')

  useEffect(() => {
    let active = true
    setLoading(true)
    
    Promise.all([
      getPliegos(syndicationId).catch(() => null),
      itemId ? getSavedAnalysis(itemId).catch(() => null) : Promise.resolve(null)
    ]).then(([weaviateData, sqlAnalysis]) => {
      if (!active) return
      setData(weaviateData)
      setAnalysis(sqlAnalysis)
      setLoading(false)
    })
    
    return () => { active = false }
  }, [syndicationId, itemId])

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
              <button className={activeTab === 'match' ? 'active' : ''} onClick={() => setActiveTab('match')}>Compatibilidad (Match)</button>
              <button className={activeTab === 'technical' ? 'active' : ''} onClick={() => setActiveTab('technical')}>Specs Técnicas (PPT)</button>
              <button className={activeTab === 'risks' ? 'active' : ''} onClick={() => setActiveTab('risks')}>Riesgos Legales (PCAP)</button>
              <button className={activeTab === 'criteria' ? 'active' : ''} onClick={() => setActiveTab('criteria')}>Criterios de Valoración</button>
            </div>

            <div className="tab-content">
              {activeTab === 'match' && (
                <div className="tab-pane">
                  <h3>Análisis de Compatibilidad (IA)</h3>
                  {analysis ? (
                    <div className="ai-content">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                        <div style={{ 
                          fontSize: '1.5rem', fontWeight: 'bold', padding: '4px 12px', borderRadius: '4px',
                          backgroundColor: analysis.veredicto === 'YES' ? '#c6f6d5' : analysis.veredicto === 'NO' ? '#fed7d7' : '#feebc8',
                          color: analysis.veredicto === 'YES' ? '#276749' : analysis.veredicto === 'NO' ? '#9b2c2c' : '#c05621'
                        }}>
                          {analysis.veredicto === 'YES' ? 'APTO' : analysis.veredicto === 'NO' ? 'NO APTO' : 'DUDOSO'}
                        </div>
                        <div style={{ fontSize: '1.1rem' }}>Match con tu Perfil</div>
                      </div>
                      
                      {analysis.razonamiento && (
                        <p style={{ marginBottom: '16px' }}>{analysis.razonamiento}</p>
                      )}
                      
                      {analysis.requisitos_evaluados && analysis.requisitos_evaluados.length > 0 && (
                        <div className="requirements-box">
                          <h4>Evaluación de Requisitos</h4>
                          <ul className="req-list">
                            {analysis.requisitos_evaluados.map((req, i) => (
                              <li key={i} className={req.cumple ? 'req-pass' : 'req-fail'}>
                                <div className="req-header">
                                  <strong>{req.cumple ? '✅' : '❌'} {req.requisito}</strong>
                                </div>
                                <div className="req-reason">{req.razon}</div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="loading-state">
                      <p>El análisis de compatibilidad se está procesando o tu perfil no está configurado.</p>
                      <p className="subtext">El análisis se ejecuta automáticamente al guardar la licitación.</p>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'technical' && (
                <div className="tab-pane">
                  <h3>Prescripciones Técnicas (PPT)</h3>
                  {analysis && analysis.ppt_json ? (
                    <div className="ai-content">
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {JSON.stringify(analysis.ppt_json, null, 2)}
                      </pre>
                    </div>
                  ) : (
                    <p>Análisis en proceso...</p>
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
                  {analysis && analysis.pcap_json ? (
                    <div className="ai-content">
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '0.9rem' }}>
                        {JSON.stringify(analysis.pcap_json, null, 2)}
                      </pre>
                    </div>
                  ) : (
                    <p>Análisis en proceso...</p>
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
        .requirements-box { background: #ffffff; border: 1px solid #e2e8f0; padding: 16px; border-radius: 6px; margin-top: 12px; }
        .req-list { list-style: none; padding: 0; margin: 0; }
        .req-list li { padding: 12px; border-bottom: 1px solid #edf2f7; }
        .req-list li:last-child { border-bottom: none; }
        .req-pass { border-left: 4px solid #48bb78; }
        .req-fail { border-left: 4px solid #f56565; background: #fff5f5; }
        .req-reason { margin-top: 6px; font-size: 0.9rem; color: #4a5568; }
        .loading-state { padding: 32px; text-align: center; color: #718096; background: #f7fafc; border-radius: 8px; border: 1px dashed #cbd5e0; }
      `}</style>
    </div>
  )
}
