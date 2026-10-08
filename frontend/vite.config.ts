/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Proxy de développement : /api → backend FastAPI (http://localhost:8000 par défaut,
// surchargeable via VITE_API_PROXY_TARGET dans .env.local).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const target = env.VITE_API_PROXY_TARGET || "http://localhost:8000";
  // `vite --mode mock` (npm run dev:mock) force le mode démonstration sans fichier .env.
  const define: Record<string, string> =
    mode === "mock" ? { "import.meta.env.VITE_USE_MOCKS": JSON.stringify("true") } : {};
  return {
    plugins: [react()],
    define,
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": { target, changeOrigin: true },
      },
    },
    preview: {
      port: 4173,
      proxy: {
        "/api": { target, changeOrigin: true },
      },
    },
    build: {
      sourcemap: false,
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks: {
            leaflet: ["leaflet", "react-leaflet"],
            charts: ["recharts"],
            react: ["react", "react-dom", "react-router-dom"],
          },
        },
      },
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts"],
    },
  };
});
