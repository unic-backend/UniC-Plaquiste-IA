import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";

/**
 * Navigation « comme une vraie appli » :
 * - retour (bouton Retour ou geste du téléphone) = on retrouve la page là où on l'avait laissée, pas tout en haut ;
 * - le retour d'Android remonte dans l'appli au lieu de la fermer (la fermeture n'arrive que depuis l'accueil).
 */
const KEY = "unic.scroll";
const MAX_ENTRIES = 80;

function read(): Record<string, number> {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function write(m: Record<string, number>) {
  try {
    const keys = Object.keys(m);
    if (keys.length > MAX_ENTRIES) for (const k of keys.slice(0, keys.length - MAX_ENTRIES)) delete m[k];
    sessionStorage.setItem(KEY, JSON.stringify(m));
  } catch { /* stockage indisponible : le retour revient simplement en haut */ }
}

export function useScrollMemory() {
  const loc = useLocation();
  const type = useNavigationType();
  const keyRef = useRef(loc.key);
  useEffect(() => {
    let t: number | undefined;
    const onScroll = (e: Event) => {
      const el = e.target as HTMLElement;
      if (!(el instanceof HTMLElement) || !el.classList.contains("page")) return;
      const top = el.scrollTop, key = keyRef.current;
      window.clearTimeout(t);
      t = window.setTimeout(() => { const m = read(); m[key] = top; write(m); }, 120);
    };
    document.addEventListener("scroll", onScroll, true);
    return () => { document.removeEventListener("scroll", onScroll, true); window.clearTimeout(t); };
  }, []);
  useLayoutEffect(() => {
    keyRef.current = loc.key;
    if (type !== "POP") return;
    const target = read()[loc.key] || 0;
    if (target <= 0) return;
    let frames = 0, raf = 0;
    const apply = () => {   // le contenu peut arriver après le premier affichage : on réessaie un instant
      const el = document.querySelector<HTMLElement>(".page");
      if (el && el.scrollHeight - el.clientHeight >= target - 1) { el.scrollTop = target; return; }
      if (++frames < 45) raf = requestAnimationFrame(apply);
      else if (el) el.scrollTop = target;
    };
    raf = requestAnimationFrame(apply);
    return () => cancelAnimationFrame(raf);
  }, [loc.key, type]);
}

function parent(path: string): string {
  if (path === "/parametres") return "/";
  if (path.startsWith("/parametres/")) return "/parametres";
  const m = /^\/(devis|factures|commandes|livraisons|chantiers|suivi)\/[^/]+/.exec(path);
  return m ? `/${m[1]}` : "/";
}

/** Le retour d'Android (MainActivity) appelle window.__unicBack : vrai = géré dans l'appli, faux = l'appli passe en arrière-plan. */
export function useBackHandler(closeLayer: () => boolean) {
  const loc = useLocation();
  const nav = useNavigate();
  const ref = useRef({ path: loc.pathname, nav, closeLayer });
  ref.current = { path: loc.pathname, nav, closeLayer };
  useEffect(() => {
    (window as any).__unicBack = () => {
      const { path, nav: go, closeLayer: close } = ref.current;
      if (close()) return true;
      if (path === "/") return false;
      const idx = (window.history.state && window.history.state.idx) || 0;
      if (idx > 0) go(-1); else go(parent(path), { replace: true });
      return true;
    };
    return () => { delete (window as any).__unicBack; };
  }, []);
}
