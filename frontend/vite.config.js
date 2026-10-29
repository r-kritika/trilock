import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api to the FastAPI backend so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: { port: Number(process.env.VITE_PORT || 5173), proxy: { '/api': process.env.VITE_BACKEND || 'http://127.0.0.1:8000' } },
})
