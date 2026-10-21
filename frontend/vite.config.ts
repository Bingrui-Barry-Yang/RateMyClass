import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// Ports come from the single .env at the repo root (see .env.example).
const repoRoot = path.resolve(import.meta.dirname, '..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')
  const backendPort = env.BACKEND_PORT ?? '8010'

  return {
    envDir: repoRoot,
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(import.meta.dirname, 'src') },
    },
    server: {
      port: Number(env.FRONTEND_PORT ?? 5173),
      strictPort: true,
      // Same-origin /api in dev, exactly like Caddy in production: no CORS needed.
      proxy: { '/api': `http://localhost:${backendPort}` },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
