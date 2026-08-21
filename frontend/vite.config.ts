import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 3000, host: true },
  build: {
    // node-seal's web build inlines the SEAL WebAssembly as base64, so it is a
    // single ~1.45 MB module with no separate .wasm fetch. That is convenient
    // for static hosting but it does trip Vite's default chunk warning, and it
    // must be split out so the login screen is not blocked behind it.
    chunkSizeWarningLimit: 2048,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node-seal")) return "seal";
          if (id.includes("react")) return "react";
        },
      },
    },
  },
});
