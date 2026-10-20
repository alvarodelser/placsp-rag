import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { AuthProvider } from './AuthContext.jsx'
import { installAuthRetry } from './authFetch.js'
import './styles.css'

installAuthRetry((import.meta.env.VITE_API_BASE || '/placsprag').replace(/\/$/, ''))

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>,
)
