import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './',
  // electron:dev espera este puerto, y el motor solo admite este origen en desarrollo (CORS).
  server: { port: 5175, strictPort: true },
})
