/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin in development: the dashboard calls /api/* and Vite proxies it.
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
  build: { sourcemap: false },
  test: { environment: "jsdom", globals: false },
});
