import { money } from '../format.js'
import cpvMap from '../codelists/cpv.json'
import nutsMap from '../codelists/nuts.json'
import { BookmarkSimple } from '../icons.js'
import PliegosModal from './PliegosModal.jsx'
import { useState } from 'react'

export default function ResultCard({ r, saved = false, onToggleSave = () => {} }) {
  const [showModal, setShowModal] = useState(false)
  const title = r.title || r.expediente || r.syndication_id || 'Sin título'
  const moneys = [
    ['Presupuesto', r.budget_amount],
    ['Valor estimado', r.estimated_value],
    ['Adjudicación', r.awarded_amount],
  ].map(([label, v]) => [label, money(v)]).filter(([, v]) => v)
  const nutsLabel = r.nuts_label || nutsMap[r.nuts] || r.city
  const loc = [nutsLabel, r.publication_date].filter(Boolean).join(' · ')

  return (
    <div className="card">
      <div className="card-main">
        {r._score != null && <span className="score">{Number(r._score).toFixed(3)}</span>}
        <div className="badges">
          {r.category && <span className="badge">{r.category}</span>}
          {r.contract_type && <span className="badge">{r.contract_type}</span>}
          {r.status_label && <span className="badge estado">{r.status_label}</span>}
        </div>
        <h2>{r.source_url
          ? <a href={r.source_url} target="_blank" rel="noopener noreferrer">{title}</a>
          : title}</h2>
        {r.contracting_authority && (
          <div className="row"><b>Órgano:</b> {r.contracting_authority}
            {r.org_top_level && r.org_top_level !== r.contracting_authority && ` · ${r.org_top_level}`}</div>
        )}
        {r.procedure && <div className="row"><b>Procedimiento:</b> {r.procedure}</div>}
        {moneys.length > 0 && (
          <div className="money">{moneys.map(([label, v]) => (
            <span key={label}><b>{label}:</b> {v}</span>))}</div>
        )}
        {Array.isArray(r.cpv) && r.cpv.length > 0 && (
          <div className="chips">{r.cpv.slice(0, 8).map((c) => (
            <span className="chip" key={c} title={cpvMap[c] || ''}>
              {c}{cpvMap[c] ? ` · ${cpvMap[c]}` : ''}</span>))}</div>
        )}
        {r.adjudicatario && <div className="row"><b>Adjudicatario:</b> {r.adjudicatario}</div>}
        {loc && <div className="row">{loc}</div>}
        {r.content && <div className="snippet">{r.content}</div>}
        <button 
          className="ai-btn" 
          onClick={() => setShowModal(true)}
          style={{ marginTop: '12px', background: '#ebf8ff', color: '#2b6cb0', border: '1px solid #bee3f8', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px', width: 'fit-content' }}
        >
          ✨ Análisis Inteligente
        </button>
      </div>
      <button
        type="button"
        className={`relgutter${saved ? ' on' : ''}`}
        onClick={onToggleSave}
        aria-pressed={saved}
        title={saved ? 'Guardado en Mi Espacio' : 'Guardar en Mi Espacio'}
      >
        <BookmarkSimple size={20} weight={saved ? 'fill' : 'regular'} />
        <span>{saved ? 'Guardado' : 'Guardar'}</span>
      </button>

      {showModal && (
        <PliegosModal 
          syndicationId={r.syndication_id} 
          title={title} 
          onClose={() => setShowModal(false)} 
        />
      )}
    </div>
  )
}
