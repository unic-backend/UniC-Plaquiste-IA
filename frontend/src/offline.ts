import { useEffect, useState } from "react";

/** Mode hors-ligne léger : une demande écrite sans réseau est gardée sur l'appareil, envoyée au retour du réseau. */
const KEY = "unic.outbox";

export function readOutbox(): string[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}

function write(list: string[]) {
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(-20))); } catch { /* stockage indisponible : on n'enregistre rien */ }
}

export function queueMessage(text: string): number { const l = [...readOutbox(), text]; write(l); return l.length; }

export function takeQueued(): string | undefined { const l = readOutbox(); const first = l.shift(); write(l); return first; }

export function useOnline(): boolean {
  const [on, setOn] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const up = () => setOn(true), down = () => setOn(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);
  return on;
}
