import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  base: '/',

  server: {
    // Proxy API calls to the FastAPI backend during local development.
    // This means the browser always talks to the Vite origin (no CORS).
    // In Docker the same path is proxied by Nginx (see nginx.conf).
    proxy: {
      '/wind-farms': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
