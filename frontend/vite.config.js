import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '^/estimates/[^/]+/export\\.xlsx$': 'http://127.0.0.1:8765'
    }
  },
  build: {
    outDir: '../src/g2b_compare/web/frontend_dist',
    emptyOutDir: true
  },
  test: {
    maxWorkers: 1,
    minWorkers: 1
  }
});
