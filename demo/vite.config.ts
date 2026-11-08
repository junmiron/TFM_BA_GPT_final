import { defineConfig } from 'vitest/config';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';

// The demo is deployed as a static SPA under the portfolio site at /ba-gpt/demo/.
// Vercel serves the built dist directory committed to the portfolio repo.
export default defineConfig({
  base: '/ba-gpt/demo/',
  plugins: [tailwindcss(), react()],
  // ui/src components import `react`; without dedupe they resolve to
  // ui/node_modules/react while demo/src uses demo/node_modules/react -
  // two React instances sharing one react-dom dispatcher is a guaranteed crash.
  resolve: { dedupe: ['react', 'react-dom'] },
  build: { outDir: 'dist', sourcemap: false },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
