import { defineConfig } from "vite";

const opsWebOrigin = process.env.OPS_WEB_ORIGIN || "https://ops.api.xenkee.com";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/api/v1/mcp-api-keys/config": {
        target: opsWebOrigin,
        changeOrigin: true,
        secure: true,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
});
