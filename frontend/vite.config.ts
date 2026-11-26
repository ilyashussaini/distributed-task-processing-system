import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: process.env.VITE_TASKFLOW_DEMO === 'true' ? undefined : {
      '/api': {
        target: process.env.DASHBOARD_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api(?=\/|$)/, ''),
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'] },
})
