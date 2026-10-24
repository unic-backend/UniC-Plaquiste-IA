import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const ROOT = fileURLToPath(new URL(".", import.meta.url));

/** Empreinte des SOURCES de l'interface (pas du paquet compilé) : l'APK et le serveur, construits à part depuis le même code,
 * portent la même. Le téléphone la compare à celle du serveur pour annoncer « nouvelle version » (voir UpdateBanner). */
function sourceBuild(): string {
  const h = createHash("sha256");
  const walk = (dir: string) => {
    for (const name of readdirSync(dir).sort()) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else h.update(relative(ROOT, p).split("\\").join("/")).update(readFileSync(p));
    }
  };
  for (const d of ["src", "public"]) {
    try { walk(join(ROOT, d)); } catch { /* dossier absent */ }
  }
  for (const f of ["index.html", "package.json", "package-lock.json"]) {
    try { h.update(f).update(readFileSync(join(ROOT, f))); } catch { /* fichier absent */ }
  }
  return h.digest("hex").slice(0, 12);
}

const BUILD = sourceBuild();

/** dist/version.json : ce que le serveur annonce comme version en ligne de l'interface. */
const versionFile = (): Plugin => ({
  name: "unic-version",
  generateBundle() {
    this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ build: BUILD }) });
  },
});

export default defineConfig({
  plugins: [react(), versionFile()],
  define: { __APP_BUILD__: JSON.stringify(BUILD) },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
  },
});
