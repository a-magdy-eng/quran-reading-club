import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the API runs on the backend port; the built app is served by the backend itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
  test: {
    environment: "node",
  },
} as any);
