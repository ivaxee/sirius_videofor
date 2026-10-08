import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { '/api': { target: process.env.API_URL || 'http://localhost:8000', changeOrigin: true } },
  },
  preview: {
    proxy: { '/api': { target: process.env.API_URL || 'http://localhost:8000', changeOrigin: true } },
  },
  build: {
    target: ['es2020', 'safari14'],
    cssCodeSplit: true,
    assetsInlineLimit: 0,
  },
});
