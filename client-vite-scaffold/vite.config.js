import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The client calls the API at /api/...; Vite forwards it to the FastAPI server,
// so there is no CORS setup to worry about in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
