import { defineConfig } from "vite";

// The shell is served at "/" by the Python server; its assets live under /cdlm/app/.
// `npm run dev` proxies /cdlm (API, WebSocket, tiles) to the Python server on :8788.
export default defineConfig({
  base: "/cdlm/app/",
  build: { outDir: "dist", emptyOutDir: true, target: "safari16" },
  server: {
    port: 5173,
    proxy: {
      "/cdlm/ws": { target: "ws://127.0.0.1:8788", ws: true },
      "^/cdlm/(?!app/)": "http://127.0.0.1:8788",
    },
  },
});
