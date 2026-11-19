import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes into the Python package so `qcc review` can serve it.
// `npm run dev` proxies /api and /files to a running `qcc review` backend (default port 8765).
const backend = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@contract": fileURLToPath(new URL("./contract", import.meta.url)),
    },
  },
  build: {
    outDir: "../src/quantcore_circuits/review/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/files": { target: backend, changeOrigin: false },
    },
  },
});
