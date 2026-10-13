import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev only: forward /api to the deployed API so the UI can run locally without CORS setup.
// Set VITE_API_URL=http://localhost:5173 in .env.local to use it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: 'https://parda-cinema-api.onrender.com', changeOrigin: true } } },
})
