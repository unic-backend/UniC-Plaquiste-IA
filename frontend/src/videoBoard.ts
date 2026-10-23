/** Studio vidéo : outils purs de l'aperçu du scénario (durées, chiffres, couleurs des ambiances), testés dans tests/videoBoard.check.ts. */

export type BoardScene = { type: string; seconds?: number; [k: string]: unknown };

/** Ambiances du moteur (scripts/video/scenes.html, garder les mêmes valeurs) : fond, texte, accent, nuance, halos, cartes de chiffres. */
export const THEMES: Record<string, { name: string; bg: string; fg: string; accent: string; soft: string; g1: string; g2: string; cardBg: string; cardFg: string }> = {
  unic: { name: "UniC", bg: "#02083a", fg: "#ffffff", accent: "#ffc400", soft: "#ffefa3", g1: "#14307f", g2: "#3a2d00", cardBg: "#ffefa3", cardFg: "#02083a" },
  night: { name: "Nuit", bg: "#05060a", fg: "#f2f4f8", accent: "#5ad1ff", soft: "#cfeaff", g1: "#12304a", g2: "#2a1245", cardBg: "#cfeaff", cardFg: "#05060a" },
  light: { name: "Clair", bg: "#f6f1e7", fg: "#1a1814", accent: "#b8612e", soft: "#6b4a2e", g1: "#ffffff", g2: "#ecd9b8", cardBg: "#1a1814", cardFg: "#f6f1e7" },
  earth: { name: "Nature", bg: "#10231a", fg: "#f4efe0", accent: "#e9b44c", soft: "#cfe3b8", g1: "#1f5a3a", g2: "#5a3a12", cardBg: "#cfe3b8", cardFg: "#10231a" },
  ocean: { name: "Océan", bg: "#04202e", fg: "#eefbff", accent: "#35d0c4", soft: "#bfeeee", g1: "#0d5a7a", g2: "#0a2a55", cardBg: "#bfeeee", cardFg: "#04202e" },
  sunset: { name: "Couchant", bg: "#2a0f1f", fg: "#fff5ee", accent: "#ff8a4c", soft: "#ffd2b8", g1: "#6a1f3a", g2: "#7a3a10", cardBg: "#ffd2b8", cardFg: "#2a0f1f" },
};

/** Durée d'une scène telle que le moteur la filme (une scène « page » : accueil + chapitres + descente finale). */
export function sceneSeconds(s: BoardScene): number {
  if (s.type === "page") {
    const ch = Array.isArray(s.chapters) ? (s.chapters as { seconds?: number }[]) : [];
    return Number(s.hero_seconds ?? 4.4) + ch.reduce((a, c) => a + Number(c.seconds || 0), 0) + 2.5;
  }
  return Number(s.seconds || 0);
}

export const totalSeconds = (scenes: BoardScene[]) => Math.round(scenes.reduce((a, s) => a + sceneSeconds(s), 0));

/** « 1 min 05 s », « 42 s ». */
export function duration(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
}

/** Chiffre comme dans la vidéo : décimales gardées (2,5), milliers groupés à partir de 10 000 (une année reste 1857). */
export function statNumber(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  const m = /\.(\d+)/.exec(String(v));
  const d = m ? Math.min(2, m[1].length) : 0;
  const a = Math.abs(n).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: Math.abs(n) >= 1e4 });
  return (n < 0 ? "−" : "") + a.replace(/ /g, " ");
}

/** Typographie française comme le moteur (scenes.html) : espace insécable avant « : ; ! ? % » et après « « », un nombre « 15 000 » ne se coupe pas. */
export const frText = (v: unknown) => String(v ?? "").replace(/\s+([:;!?»%])/g, "\u00a0$1").replace(/«\s+/g, "«\u00a0").replace(/(\d) (?=\d{3}(?!\d))/g, "$1\u00a0");
