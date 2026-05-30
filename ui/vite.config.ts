import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

const uiDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(uiDir, "..");

export default defineConfig(({ mode }) => {
  const rootEnv = loadEnv(mode, repoRoot, "");
  const uiEnv = loadEnv(mode, uiDir, "");
  // THINA_PORT no .env da raiz; ui/.env.development (VITE_THINA_PORT); senão 8081
  const thinaPort = rootEnv.THINA_PORT || uiEnv.VITE_THINA_PORT || "8081";
  const apiTarget = `http://127.0.0.1:${thinaPort}`;

  console.log(`[thina-ui] Proxy API → ${apiTarget} (THINA_PORT do .env na raiz)`);

  return {
    base: "/ui/",
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/health": { target: apiTarget, changeOrigin: true },
        "/v1": { target: apiTarget, changeOrigin: true },
        // Se algum fetch cair em /ui/v1/... (base href), reencaminha para a API
        "/ui/health": {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/ui/, ""),
        },
        "/ui/v1": {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/ui/, ""),
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
