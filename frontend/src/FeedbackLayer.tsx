import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ACTION_SELECTOR, isDoubleTap, netSnapshot, noticeSnapshot, subscribeNet, subscribeNotice } from "./feedback";

const SHOW_AFTER_MS = 140;   // en dessous, la réponse paraît instantanée : pas de barre qui clignote
const SLOW_AFTER_MS = 4000;  // au-delà, on le dit

const TAP_TARGET = "button, a[href], [role=button], summary, .btn";

/** Couche d'accueil du toucher : barre d'activité réseau, message « serveur lent », notices, éclat d'appui, garde anti double-appui. */
export default function FeedbackLayer() {
  const net = useSyncExternalStore(subscribeNet, netSnapshot);
  const text = useSyncExternalStore(subscribeNotice, noticeSnapshot);
  const [, tick] = useState(0);
  const last = useRef<{ el: unknown; t: number } | null>(null);

  // la barre n'apparaît qu'après un court délai : on réévalue pendant que des requêtes sont en cours
  useEffect(() => {
    if (!net.pending) return;
    const id = setInterval(() => tick((n) => n + 1), 400);
    return () => clearInterval(id);
  }, [net.pending]);

  useEffect(() => {
    // éclat visible APRÈS le relâchement : l'état :active ne dure que quelques millisecondes
    const flash = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.(TAP_TARGET) as HTMLElement | null;
      if (!el || (el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true") return;
      el.classList.remove("tap-flash");
      void el.offsetWidth;   // relance l'animation si on retouche aussitôt
      el.classList.add("tap-flash");
      setTimeout(() => el.classList.remove("tap-flash"), 320);
    };
    // deuxième appui sur le même bouton d'action en moins de 350 ms : ignoré (sinon doublons : 2 devis, 2 envois…)
    const guard = (e: MouseEvent) => {
      const el = (e.target as Element | null)?.closest?.(ACTION_SELECTOR);
      if (!el) return;
      const now = Date.now();
      if (isDoubleTap(last.current, el, now)) { e.stopPropagation(); e.preventDefault(); return; }
      last.current = { el, t: now };
    };
    document.addEventListener("pointerdown", flash, true);
    document.addEventListener("click", guard, true);
    return () => { document.removeEventListener("pointerdown", flash, true); document.removeEventListener("click", guard, true); };
  }, []);

  const age = net.pending && net.since ? Date.now() - net.since : 0;
  const bar = net.pending > 0 && age >= SHOW_AFTER_MS;
  const slow = net.pending > 0 && (age >= SLOW_AFTER_MS || !!net.note);
  return (
    <>
      <div className={`net-bar${bar ? " on" : ""}`} aria-hidden="true" />
      {slow && <div className="net-slow" role="status">{net.note || "Le serveur met du temps à répondre… ne touche pas deux fois, ça arrive."}</div>}
      {text && <div className="toast toast-global" role="status">{text}</div>}
    </>
  );
}
