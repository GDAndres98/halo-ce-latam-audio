import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Development only. The dev server forwards /api and /audio to the API server's local address (127.0.0.1:8765,
// the host's own administrator address); both run on this computer only, and Vite listens on localhost only.
// Never expose the dev server: other computers use the production server (`npm run host`, docs/remote-access.md),
// which serves the built page and the API from one address with sign-in.
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
