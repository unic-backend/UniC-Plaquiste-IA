import { useEffect, useState } from "react";

export type ThemeMode = "auto" | "light" | "dark";
const KEY = "unic.theme";

export function getMode(): ThemeMode {
  try { const v = localStorage.getItem(KEY); if (v === "light" || v === "dark") return v; } catch { /* ignoré */ }
  return "auto";
}

const systemDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

/** Applique le thème et la couleur de la barre du navigateur / système. */
export function applyTheme(mode: ThemeMode = getMode()): void {
  const dark = mode === "dark" || (mode === "auto" && systemDark());
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0d1210" : "#1A2320");
  import("@capacitor/status-bar")
    .then(({ StatusBar, Style }) => StatusBar.setStyle({ style: Style.Dark }).catch(() => {}))
    .catch(() => {});
}

export function setMode(mode: ThemeMode): void {
  try { if (mode === "auto") localStorage.removeItem(KEY); else localStorage.setItem(KEY, mode); } catch { /* ignoré */ }
  applyTheme(mode);
}

export function useTheme(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, set] = useState<ThemeMode>(getMode());
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => { if (getMode() === "auto") applyTheme("auto"); };
    mq?.addEventListener("change", onChange);
    return () => mq?.removeEventListener("change", onChange);
  }, []);
  return [mode, (m) => { setMode(m); set(m); }];
}
