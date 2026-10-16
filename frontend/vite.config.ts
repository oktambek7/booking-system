import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

declare const process: { env: Record<string, string | undefined> }   // Node's, without pulling in @types/node

// Dev only: forward /api to the deployed API (the Render service keeps its original name until it is renamed) so the UI can run locally without CORS setup.
// Set VITE_API_URL=http://localhost:5173 in .env.local to use it.
export default defineConfig({
  plugins: [react()],
  // Which commit this build is (Vercel provides it), shown in the ?diag=1 panel so a deploy can be checked in the browser.
  define: { __BUILD__: JSON.stringify((process.env.VERCEL_GIT_COMMIT_SHA ?? 'local').slice(0, 7)) },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
  server: { proxy: { '/api': { target: 'https://parda-cinema-api.onrender.com', changeOrigin: true } } },
})
