/**
 * Croquis Sketchy dans le chat : l'IA écrit un bloc ```sketchy (quoi dessiner), le moteur place tout (où dessiner).
 * Le moteur (2,5 Mo, public/vendor/sketchy) n'est chargé qu'au premier croquis, depuis l'appli elle-même : aucun CDN.
 */
type SketchyApi = { draw: (target: HTMLElement, scene: string) => Promise<void> };
let loading: Promise<SketchyApi> | null = null;

function load(): Promise<SketchyApi> {
  loading ??= new Promise<SketchyApi>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `${import.meta.env.BASE_URL}vendor/sketchy/sketchy.js`;
    s.onload = () => { const api = (window as any).Sketchy; api ? resolve(api) : reject(new Error("Sketchy absent")); };
    s.onerror = () => { loading = null; reject(new Error("Croquis indisponible")); };
    document.head.appendChild(s);
  });
  return loading;
}

/** Dessine les blocs .sketchy pas encore dessinés ; en cas d'échec, le texte de la scène reste affiché. */
export function drawSketches(root: HTMLElement | null) {
  const blocks = root ? Array.from(root.querySelectorAll<HTMLElement>(".sketchy[data-scene]:not([data-drawn])")) : [];
  if (!blocks.length) return;
  load().then((api) => {
    for (const el of blocks) {
      if (!el.isConnected || el.dataset.drawn) continue;
      el.dataset.drawn = "1";
      const scene = el.dataset.scene || "";
      el.textContent = "";
      api.draw(el, scene).catch(() => { el.textContent = scene; });
    }
  }, () => { /* hors ligne ou fichier manquant : le texte de la scène reste visible */ });
}
