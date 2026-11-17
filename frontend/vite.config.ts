import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  // Tailwind v4 只作用于显式 `@import 'tailwindcss/...'` 的样式文件（目前仅 src/lab/styles/lab.css），
  // 既有组件的普通 CSS 不受影响（无 preflight 注入）。
  plugins: [react(), tailwindcss(), tsconfigPaths()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/testing/setup.ts',
  },
})
