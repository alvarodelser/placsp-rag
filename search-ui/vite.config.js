import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_API_BASE points the UI at the search-api backend (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
