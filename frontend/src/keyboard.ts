/** Clavier du téléphone : mesure la place qu'il prend (visualViewport) et la publie en CSS.
 *  --kb  : hauteur cachée par le clavier (0 s'il est fermé ou si le système a déjà réduit la page)
 *  --vvh : hauteur encore visible
 *  Puis ramène le champ où l'on tape dans la partie visible. */

const MIN_KB = 80; // en dessous : barre d'adresse ou arrondi, pas un clavier

function editable(el: Element | null): el is HTMLElement {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable) return true;
  if (el instanceof HTMLTextAreaElement) return !el.readOnly && !el.disabled;
  if (el instanceof HTMLInputElement) {
    return !el.readOnly && !el.disabled && !/^(button|submit|reset|checkbox|radio|range|file|color|image|hidden)$/.test(el.type);
  }
  return false;
}

/** Hauteur cachée par le clavier, en pixels de la page. Zoom au doigt : on ne compte rien. */
export function keyboardInset(layoutH: number, vvH: number, vvTop: number, scale = 1): number {
  if (scale > 1.05) return 0;
  const kb = Math.round(layoutH - vvH - vvTop);
  return kb >= MIN_KB ? kb : 0;
}

export function installKeyboardInset(): void {
  if (typeof window === "undefined") return;
  const vv = window.visualViewport;
  if (!vv) return;
  const root = document.documentElement;
  let lastKb = -1;
  let lastH = -1;
  let revealTimer = 0;

  // le champ actif doit être entièrement dans la partie visible (au-dessus du clavier)
  const reveal = () => {
    const el = document.activeElement;
    if (!editable(el)) return;
    const r = el.getBoundingClientRect();
    const top = vv.offsetTop;
    const bottom = vv.offsetTop + vv.height;
    if (r.bottom > bottom - 8 || r.top < top) {
      el.scrollIntoView({ block: r.height > vv.height * 0.6 ? "start" : "nearest", inline: "nearest" });
    }
  };

  const update = () => {
    const kb = editable(document.activeElement) ? keyboardInset(window.innerHeight, vv.height, vv.offsetTop, vv.scale) : 0;
    const h = Math.round(vv.height);
    if (kb !== lastKb) {
      lastKb = kb;
      root.style.setProperty("--kb", `${kb}px`);
      root.classList.toggle("kb-open", kb > 0);
    }
    if (h !== lastH) {
      lastH = h;
      root.style.setProperty("--vvh", `${h}px`);
    }
    // après la transition de la mise en page (.18 s), on vérifie que le champ se voit
    window.clearTimeout(revealTimer);
    revealTimer = window.setTimeout(reveal, 240);
  };

  vv.addEventListener("resize", update);
  vv.addEventListener("scroll", update);
  window.addEventListener("resize", update);
  // le clavier s'ouvre un peu après le toucher : on revérifie une fois qu'il est monté
  document.addEventListener("focusin", () => { update(); window.setTimeout(update, 350); });
  // passage d'un champ à l'autre : on attend que le nouveau champ soit actif avant de remettre à 0
  document.addEventListener("focusout", () => { window.setTimeout(update, 60); });
  update();
}
