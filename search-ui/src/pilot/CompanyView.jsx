// search-ui/src/pilot/CompanyView.jsx — one company or authority across every expediente of the pilot.
import { useEffect, useState } from 'react'
import { getCompany } from './pilotApi.js'
import { CHANNEL, COMPANY_ROLE } from './labels.js'
import { money } from '../format.js'
import { CircleNotch } from '../icons.js'
import { go } from './route.js'

export default function CompanyView({ id }) {
  const [state, setState] = useState({ status: 'loading' })
  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    getCompany(id).then((d) => live && setState({ status: 'done', d })).catch((e) => live && setState({ status: 'error', e: e.message }))
    return () => { live = false }
  }, [id])
  if (state.status === 'loading') return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  if (state.status === 'error') return <div className="err">{state.e}</div>
  const { node, tenders, rivals, authorities } = state.d
  const roles = {}
  tenders.forEach((t) => t.roles.forEach((r) => { roles[r] = (roles[r] || 0) + 1 }))

  return (
    <div className="tv">
      <div className="tv-head">
        <div className="badges">{(node.kinds || []).map((k) => <span key={k} className="badge">{k}</span>)}</div>
        <h2>{node.name}</h2>
        <div className="row">{node.nif ? <>NIF <b>{node.nif}</b></> : 'Sin NIF: identificada por nombre'}
          {(node.aliases || []).length > 1 && <span className="muted"> · también: {node.aliases.filter((a) => a !== node.name).slice(0, 4).join(' · ')}</span>}
        </div>
        <div className="tv-counts">
          <span><b>{tenders.length}</b> expedientes</span>
          {Object.entries(roles).map(([r, n]) => <span key={r}><b>{n}</b> como {COMPANY_ROLE[r] || r}</span>)}
        </div>
        {node.description && <p className="tv-desc">{node.description}</p>}
      </div>
      <div className="tv-grid">
        <section className="tv-card wide">
          <h3>Expedientes</h3>
          <table className="ptable">
            <thead><tr><th>Publicado</th><th>Expediente</th><th>Órgano</th><th>Papel</th><th>Valor</th></tr></thead>
            <tbody>
              {tenders.map((t) => (
                <tr key={t.tender_id}>
                  <td className="nowrap">{t.published}</td>
                  <td><button type="button" className="linkish" onClick={() => go(`/t/${t.tender_id}`)}>{t.name}</button>
                    <div className="muted small">{CHANNEL[t.channel] || t.channel} · {t.status}</div></td>
                  <td className="small">{t.authority}</td>
                  <td>{t.roles.map((r) => <span key={r} className={`chip role-${r}`}>{COMPANY_ROLE[r] || r}</span>)}</td>
                  <td className="num">{money(t.value) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="tv-card">
          <h3>Compite con</h3>
          {rivals.length === 0 ? <p className="muted small">Sin licitaciones compartidas en el piloto.</p> : (
            <ul className="plain">{rivals.map((r) => <li key={r.id}><button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(r.id)}`)}>{r.name}<span className="muted"> · {r.tenders}</span></button></li>)}</ul>
          )}
        </section>
        <section className="tv-card">
          <h3>Órganos de contratación</h3>
          {authorities.length === 0 ? <p className="muted small">—</p> : (
            <ul className="plain">{authorities.map((a) => <li key={a.id}><button type="button" className="linkish" onClick={() => go(`/c/${encodeURIComponent(a.id)}`)}>{a.name}<span className="muted"> · {a.tenders}</span></button></li>)}</ul>
          )}
        </section>
      </div>
    </div>
  )
}
