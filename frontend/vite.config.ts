import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// The API server (scripts/ui/m4_server.py) refuses requests from other hosts. The dev server forwards
// /api and /audio to it; both run locally. Start both with `npm run dev` from this folder.
// STUDIO_API lets the end-to-end test point the UI at a disposable API server (see e2e/run.mjs).
const API = process.env.STUDIO_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/audio": { target: API, changeOrigin: true },
    },
  },
});
