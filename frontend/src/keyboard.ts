/** Clavier du téléphone : mesure la place qu'il prend et la publie en CSS, sur TOUS les écrans de l'appli.
 *  --kb  : hauteur cachée par le clavier (0 s'il est fermé ou si le système a déjà réduit la page)
 *  --vvh : hauteur encore visible
 *  Puis ramène le champ où l'on tape dans la partie visible.
 *  Appli Android : la page n'est pas réduite par le système (Keyboard resize « none ») et visualViewport ne bouge pas ;
 *  la hauteur vient donc du plugin Keyboard de Capacitor (avant : lue seulement dans le chat, le Studio et les formulaires
 *  restaient cachés sous le clavier). */

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

/** De combien faire défiler pour que le champ [top, bottom] tienne dans la partie visible [visTop, visBottom] (marge comprise).
 *  > 0 : descendre la page ; < 0 : la remonter ; 0 : déjà visible. Un grand champ (plus de 60 % du visible) : on montre son haut. */
export function revealDelta(top: number, bottom: number, visTop: number, visBottom: number, margin = 12): number {
  const room = visBottom - visTop;
  if (room <= 0) return 0;
  if (bottom - top > room * 0.6) return Math.round(top - visTop - margin);
  if (bottom > visBottom - margin) return Math.round(bottom - (visBottom - margin));
  if (top < visTop + margin) return Math.round(top - visTop - margin);
  return 0;
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
  let nativeKb = 0;   // hauteur donnée par le plugin Keyboard (appli Android) : la page, elle, n'est pas réduite

  // ce qui défile autour du champ (la liste, la feuille…), sinon la page entière
  const scroller = (el: HTMLElement): HTMLElement => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const oy = getComputedStyle(p).overflowY;
      if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight + 1) return p;
    }
    return (document.scrollingElement as HTMLElement) || document.documentElement;
  };

  // le champ actif doit être entièrement dans la partie visible (au-dessus du clavier)
  const reveal = () => {
    const el = document.activeElement;
    if (!editable(el)) return;
    const r = el.getBoundingClientRect();
    const d = revealDelta(r.top, r.bottom, vv.offsetTop, vv.offsetTop + vv.height - nativeKb);
    if (d) scroller(el).scrollBy({ top: d, behavior: "smooth" });
  };

  const update = () => {
    const kb = editable(document.activeElement) ? Math.max(nativeKb, keyboardInset(window.innerHeight, vv.height, vv.offsetTop, vv.scale)) : 0;
    const h = Math.round(vv.height) - nativeKb;
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

  // appli Android : hauteur du clavier donnée par le système, pour tous les écrans (pas seulement le chat)
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  if (cap?.isNativePlatform?.()) {
    import("@capacitor/keyboard").then(({ Keyboard }) => {
      const set = (h: number) => { nativeKb = Math.max(0, Math.round(h)); update(); window.setTimeout(reveal, 120); };
      Keyboard.addListener("keyboardWillShow", (i) => set(i.keyboardHeight));
      Keyboard.addListener("keyboardDidShow", (i) => set(i.keyboardHeight));   // hauteur définitive (suggestions du clavier comprises)
      Keyboard.addListener("keyboardWillHide", () => set(0));
    }).catch(() => { /* plugin absent : la mesure de visualViewport reste */ });
  }
}
