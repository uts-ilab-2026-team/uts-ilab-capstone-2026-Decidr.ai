import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Vite config — https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // The FastAPI backend (decidr/api) serves everything under /api.
    proxy: {
      '/api': process.env.DECIDR_API_URL || 'http://127.0.0.1:8000',
    },
  },
})
