/** Retour immédiat au toucher : ce que l'utilisateur doit VOIR dès qu'il appuie, même quand le serveur met du temps à répondre.
 *
 * Pourquoi : un appui qui ne change rien à l'écran pendant 1 s est vécu comme « ça n'a pas marché » → on retouche 2-3 fois.
 * Mesuré : le serveur répond en 0,65 à 0,7 s par requête depuis l'extérieur ; sans signe de vie, chaque bouton paraît mort.
 */

type Listener = () => void;

// ---------- activité réseau ----------
let pending = 0;
let since = 0;
let note = "";
// Instantané IMMUABLE : `useSyncExternalStore` compare par identité, un objet neuf à chaque lecture provoquerait une boucle de rendu infinie.
let snap = { pending: 0, since: 0, note: "" };
const netListeners = new Set<Listener>();
const emitNet = () => {
  if (snap.pending !== pending || snap.since !== since || snap.note !== note) snap = { pending, since, note };
  netListeners.forEach((f) => f());
};

/** À appeler au début d'une requête ; rend la fonction à appeler à la fin (idempotente). */
export function netStart(): () => void {
  if (pending === 0) since = Date.now();
  pending += 1;
  emitNet();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    pending = Math.max(0, pending - 1);
    if (pending === 0) { since = 0; note = ""; }
    emitNet();
  };
}
/** Message pendant une attente anormale (ex. serveur qui redémarre). */
export function netNote(text: string): void { note = text; emitNet(); }
export function netSnapshot(): { pending: number; since: number; note: string } { return snap; }
export function subscribeNet(fn: Listener): () => void { netListeners.add(fn); return () => { netListeners.delete(fn); }; }

// ---------- notice globale (toast non bloquant) ----------
let notice = "";
let noticeTimer: ReturnType<typeof setTimeout> | undefined;
const noticeListeners = new Set<Listener>();
/** Affiche un court message à l'écran (remplace `alert`, qui bloque et demande un appui de plus). */
export function notify(text: string, ms = 3200): void {
  notice = text;
  noticeListeners.forEach((f) => f());
  if (noticeTimer) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice = ""; noticeListeners.forEach((f) => f()); }, ms);
}
export function noticeSnapshot(): string { return notice; }
export function subscribeNotice(fn: Listener): () => void { noticeListeners.add(fn); return () => { noticeListeners.delete(fn); }; }

// ---------- garde anti double-appui ----------
export const DOUBLE_TAP_MS = 350;
/** Vrai si ce clic est un deuxième appui sur le MÊME bouton presque aussitôt : il ne doit pas relancer l'action (doublon). */
export function isDoubleTap(prev: { el: unknown; t: number } | null, el: unknown, now: number, gap = DOUBLE_TAP_MS): boolean {
  return !!prev && prev.el === el && now - prev.t < gap;
}

/** Boutons d'ACTION concernés par la garde (pas les champs, pas les curseurs, pas les compteurs +/-). */
export const ACTION_SELECTOR = "button.btn, button.doc-act, button.quick-chip, button.send, button[type=submit], .app-row, .hub-item";
