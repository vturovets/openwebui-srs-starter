import { defineConfig } from 'vite';
import { svelte } from 'vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 4173,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
  },
});

