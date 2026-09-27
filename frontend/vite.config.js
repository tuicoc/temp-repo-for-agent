import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production the FastAPI app serves this build from the same origin, so the
// client calls /api with a relative path and there is no CORS to configure.
// The proxy below only exists so that `npm run dev` behaves the same way
// against a backend on another port.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // ws: the hotline channel's audio runs over a WebSocket under /api.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
      // The admin page renders the service's own health report.
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
