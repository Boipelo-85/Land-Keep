<<<<<<< HEAD
import { defineConfig, loadEnv } from 'vite'
=======
import { defineConfig } from 'vite'
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
import react from '@vitejs/plugin-react'

// The client calls the API at /api/...; Vite forwards it to the FastAPI server,
// so there is no CORS setup to worry about in development.
<<<<<<< HEAD
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
=======
export default defineConfig({
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
<<<<<<< HEAD
        target: env.LANDKEEP_API_TARGET || 'http://127.0.0.1:8000',
=======
        target: 'http://localhost:8000',
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
<<<<<<< HEAD
  }
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
})
