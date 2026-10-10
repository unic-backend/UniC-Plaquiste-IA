import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Le serveur de développement peut être consulté depuis un hôte distant (aperçu en ligne, poste de travail).
    // Vite refuse par défaut les noms d'hôte inconnus : sans cette ligne, la page affiche « Blocked request ».
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
  },
});
