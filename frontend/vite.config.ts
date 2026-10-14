import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";

// Development only. The dev server forwards /api and /audio to the API server's local address (127.0.0.1:8765,
// the host's own administrator address); both run on this computer only, and Vite listens on localhost only.
// Never expose the dev server: other computers use the production server (`npm run host`, docs/remote-access.md),
// which serves the built page and the API from one address with sign-in.
// STUDIO_API lets the end-to-end test point the UI at a disposable API server (see e2e/run.mjs).
const API = process.env.STUDIO_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [
    vue(),
    // Installable app (docs/mobile.md §9). The service worker keeps only the Studio's own built files (the app
    // shell: scripts, styles, fonts, icons, the page), so the app opens and can say "the host is unreachable"
    // when the host computer is off. It never stores or answers /api, /audio or /classic: decisions,
    // recordings, sessions and every API answer always come from the host. Built files only (not in `vite`
    // development), and only on a secure address (https or this computer).
    VitePWA({
      registerType: "prompt", // a new version waits for "Reload" (or the next launch): never mid-edit
      injectRegister: false, // registered by src/pwa.ts
      // Behind Cloudflare Access (docs/deploy-cloudflare.md) the manifest needs the Access cookie, which browsers
      // only send for a manifest link with crossorigin="use-credentials".
      useCredentials: true,
      includeAssets: ["favicon.svg", "icons/favicon-32.png", "icons/apple-touch-icon-180.png"],
      manifest: {
        id: "./",
        name: "Halo CE Localization Studio",
        short_name: "Halo Studio",
        description: "Match Halo CE (MCC) dialogue with Latin American Spanish recordings and subtitles.",
        start_url: "./#/match",
        scope: "./",
        display: "standalone",
        orientation: "any",
        background_color: "#01040c",
        theme_color: "#030b1f",
        categories: ["productivity", "utilities"],
        icons: [
          { src: "icons/pwa-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icons/pwa-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
          { src: "icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallback: "index.html",
        // Server routes are never answered by the worker, not even a navigation to them.
        navigateFallbackDenylist: [/^\/api\//, /^\/audio\//, /^\/classic/],
        runtimeCaching: [], // nothing is cached at run time: only the precached app shell above
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/audio": { target: API, changeOrigin: true },
    },
  },
});
