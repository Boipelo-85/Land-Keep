import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The client calls the API at /api/...; Vite forwards it to the FastAPI server,
// so there is no CORS setup to worry about in development.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: env.LANDKEEP_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  }
})
