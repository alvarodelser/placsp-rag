import React, { useState, useEffect } from 'react'

export default function UserProfile({ onClose }) {
  const [profile, setProfile] = useState({
    company_name: '',
    description: '',
    cpvs: '',
    certifications: '',
    tech_stack: '',
    employees: []
  })
  
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    fetch('/api/users/me/profile', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
      .then(r => r.json())
      .then(data => {
        if (data.profile && Object.keys(data.profile).length > 0) {
          setProfile({
            ...data.profile,
            employees: data.profile.employees || []
          })
        }
        setLoading(false)
      })
      .catch(err => {
        setError("Error al cargar perfil: " + err.message)
        setLoading(false)
      })
  }, [])

  const handleChange = (e) => {
    const { name, value } = e.target
    setProfile(prev => ({ ...prev, [name]: value }))
  }

  const handleAddEmployee = () => {
    setProfile(prev => ({
      ...prev,
      employees: [...prev.employees, { name: '', profile_desc: '' }]
    }))
  }

  const handleEmployeeChange = (index, field, value) => {
    const newEmp = [...profile.employees]
    newEmp[index][field] = value
    setProfile(prev => ({ ...prev, employees: newEmp }))
  }

  const handleRemoveEmployee = (index) => {
    const newEmp = [...profile.employees]
    newEmp.splice(index, 1)
    setProfile(prev => ({ ...prev, employees: newEmp }))
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSuccess(false)
    
    try {
      const r = await fetch('/api/users/me/profile', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify(profile)
      })
      if (!r.ok) throw new Error("Error al guardar perfil")
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content profile-modal">
        <button className="close-btn" onClick={onClose}>×</button>
        <h2>Mi Perfil de Empresa</h2>
        <p className="subtitle">
          Esta información es utilizada por la IA para evaluar automáticamente si cumples los requisitos de una licitación cuando la guardas.
        </p>
        
        {loading ? <p>Cargando...</p> : (
          <form onSubmit={handleSave}>
            {error && <div className="err">{error}</div>}
            {success && <div className="success">¡Perfil guardado correctamente!</div>}
            
            <div className="form-group">
              <label>Nombre de la Empresa</label>
              <input type="text" name="company_name" value={profile.company_name} onChange={handleChange} placeholder="Ej. Tech Solutions SL" />
            </div>

            <div className="form-group">
              <label>Descripción General</label>
              <textarea name="description" value={profile.description} onChange={handleChange} rows="3" placeholder="A qué se dedica la empresa, volumen de facturación, años de experiencia..." />
            </div>
            
            <div className="form-group">
              <label>CPVs de Interés</label>
              <input type="text" name="cpvs" value={profile.cpvs} onChange={handleChange} placeholder="Ej. 72200000, 48000000" />
            </div>

            <div className="form-group">
              <label>Certificaciones y Estándares</label>
              <input type="text" name="certifications" value={profile.certifications} onChange={handleChange} placeholder="Ej. ISO 9001, ISO 27001, ENS Categoría Media" />
            </div>

            <div className="form-group">
              <label>Stack Tecnológico / Herramientas</label>
              <textarea name="tech_stack" value={profile.tech_stack} onChange={handleChange} rows="2" placeholder="React, Node.js, AWS, Kubernetes..." />
            </div>

            <div className="employees-section">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label style={{ margin: 0 }}>Perfiles de Empleados</label>
                <button type="button" className="btn-small" onClick={handleAddEmployee}>+ Añadir Empleado</button>
              </div>
              <p className="hint">Añade los perfiles clave de tu equipo para validar si cumples los requisitos de solvencia técnica.</p>
              
              {profile.employees.map((emp, i) => (
                <div key={i} className="employee-row">
                  <input type="text" placeholder="Nombre" value={emp.name} onChange={e => handleEmployeeChange(i, 'name', e.target.value)} style={{ flex: '1' }} />
                  <input type="text" placeholder="Perfil (ej. Senior Java, 10 años)" value={emp.profile_desc} onChange={e => handleEmployeeChange(i, 'profile_desc', e.target.value)} style={{ flex: '2' }} />
                  <button type="button" className="btn-remove" onClick={() => handleRemoveEmployee(i)}>×</button>
                </div>
              ))}
            </div>

            <div className="form-actions">
              <button type="submit" disabled={saving}>{saving ? 'Guardando...' : 'Guardar Perfil'}</button>
            </div>
          </form>
        )}

        <style>{`
          .profile-modal { max-width: 600px; width: 100%; max-height: 90vh; overflow-y: auto; }
          .subtitle { color: #4a5568; font-size: 0.9rem; margin-bottom: 24px; }
          .form-group { margin-bottom: 16px; }
          .form-group label { display: block; font-weight: 600; margin-bottom: 4px; font-size: 0.9rem; }
          .form-group input, .form-group textarea { width: 100%; padding: 8px; border: 1px solid #e2e8f0; border-radius: 4px; font-family: inherit; }
          .employees-section { background: #f7fafc; padding: 16px; border-radius: 6px; border: 1px solid #edf2f7; margin-bottom: 24px; }
          .hint { font-size: 0.8rem; color: #718096; margin-bottom: 12px; }
          .employee-row { display: flex; gap: 8px; margin-bottom: 8px; }
          .employee-row input { padding: 6px; border: 1px solid #cbd5e0; border-radius: 4px; }
          .btn-small { background: #edf2f7; border: 1px solid #cbd5e0; border-radius: 4px; padding: 4px 8px; font-size: 0.8rem; cursor: pointer; }
          .btn-remove { background: #fed7d7; border: none; color: #9b2c2c; border-radius: 4px; cursor: pointer; width: 28px; }
          .form-actions { text-align: right; }
          .form-actions button { background: #3182ce; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-weight: 600; cursor: pointer; }
          .form-actions button:disabled { opacity: 0.7; cursor: not-allowed; }
          .success { background: #c6f6d5; color: #276749; padding: 12px; border-radius: 4px; margin-bottom: 16px; font-weight: 600; }
        `}</style>
      </div>
    </div>
  )
}
