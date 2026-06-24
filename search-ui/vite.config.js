import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/placsprag/',
  server: {
    port: 5173,
    proxy: {
      // In dev, forward /placsprag/api/* → http://localhost:8092/api/*
      '/placsprag': {
        target: 'http://localhost:8092',
        rewrite: (path) => path.replace(/^\/placsprag/, ''),
        changeOrigin: true,
      },
    },
  },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test-setup.js' },
})
