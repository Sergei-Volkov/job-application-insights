/// <reference types="vitest" />

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    test: {
      environment: 'jsdom',
      globals: false,
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (id.includes('recharts')) return 'charts'
            return 'vendor'
          },
        },
      },
    },
    server: {
      proxy: {
        '/api': {
          target: proxyTarget,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
