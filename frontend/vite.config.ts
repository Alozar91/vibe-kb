import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Публичный адрес — https://merch-vibe.ru/know (deployment.md §1.1);
// в dev — root, проксирование API на backend.
export default defineConfig({
  plugins: [react()],
  base: '/know/',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8899', // стенд: nginx проксирует /auth → keycloak
        changeOrigin: true,
      },
    },
  },
  test: {
    setupFiles: './tests/setup.ts',
    environment: 'jsdom',
    globals: false,
  },
})
