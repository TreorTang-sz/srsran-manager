import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev mode: `npm run dev` (vite on :5173) proxies API/WS to the backend.
// Production: `npm run build` -> dist/ served by FastAPI (or nginx).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8080', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
  },
})
