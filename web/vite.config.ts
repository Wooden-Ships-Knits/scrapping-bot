/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs separately (`make serve`); Vite proxies /api to it.
const API = process.env.SCRAPEBOT_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": API } },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
