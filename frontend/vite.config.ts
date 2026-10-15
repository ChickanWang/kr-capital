import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app calls the API under /api; Vite forwards those requests to FastAPI, so no CORS setup is
// needed. API_URL is http://api:8000 inside docker-compose.
const apiUrl = process.env.API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiUrl, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
    },
  },
})
