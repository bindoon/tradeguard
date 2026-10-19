import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // Use absolute paths so that sub-routes (e.g. /stock/000001) resolve assets correctly
  base: '/',
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: 'assets/[name].[hash].[ext]',
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5178,
    // Proxy API calls to the FastAPI backend during development
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8188',
        changeOrigin: true,
      },
    },
  },
});
