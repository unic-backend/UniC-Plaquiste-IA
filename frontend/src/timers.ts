import { isNative } from "./api";

/** Minuteurs à la voix (idée reprise de ming-voice) : « minuteur 20 minutes », « rappelle-moi dans 10 minutes de vérifier l'enduit »,
 *  « combien de temps il reste au minuteur », « annule le minuteur ». Sur le téléphone : notification locale qui sonne même appli fermée ;
 *  dans le navigateur : sonnerie tant que la page reste ouverte. Tout reste sur le téléphone (rien n'est envoyé au serveur). */
export type Timer = { id: number; end: number; label: string };
export type TimerCmd = { action: "start"; seconds: number; label: string } | { action: "cancel" } | { action: "list" };

const KEY = "unic.timers";
const BASE = 5300;   // identifiants des notifications : 5300 à 5399 (agenda 5000-5199, encaissements 6000-6199, briefing 4200)
const MAX_S = 24 * 3600;
const WORDS: Record<string, number> = {
  un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6, sept: 7, huit: 8, neuf: 9, dix: 10, onze: 11, douze: 12, quinze: 15,
  vingt: 20, "vingt-cinq": 25, trente: 30, quarante: 40, "quarante-cinq": 45, cinquante: 50, soixante: 60,
};
const NUM = `(\\d+(?:[.,]\\d+)?|${Object.keys(WORDS).sort((a, b) => b.length - a.length).join("|")})`;
const UNIT_RE = new RegExp(`\\b${NUM}\\s*(heures?|h|minutes?|mins?|mn|secondes?|sec|s)(?![a-zà-ÿ])(?:\\s*(\\d{1,2})\\b(?!\\s*(?:h|heures?|min|mn|s|sec)))?`, "gi");
const START_RE = /\b(minuteur|chrono(?:m[eè]tre)?|timer|compte [àa] rebours)\b|\b(?:rappelle|pr[ée]viens|avertis|r[ée]veille)[- ]?moi\s+dans\b|\bdans\b.{0,30}\b(?:rappelle|pr[ée]viens|avertis|r[ée]veille)[- ]?moi\b/i;
const CANCEL_RE = /\b(annule|arr[êe]te|stoppe|supprime|enl[eè]ve|coupe)\w*\b.{0,25}\b(minuteurs?|chronos?|timers?|rappels?|comptes? [àa] rebours)\b/i;
const LIST_RE = /\b(minuteurs?|chronos?|timers?)\b/i;
const ASK_RE = /\b(combien|reste|restant|o[uù] en est|quels?|liste|en cours)\b/i;

const num = (s: string): number => WORDS[s.toLowerCase()] ?? Number(s.replace(",", "."));

/** Durée dite (« 1 h 30 », « 1h30 », « une demi-heure », « vingt minutes », « 90 secondes ») → secondes ; 0 si aucune. */
export function duration(text: string): number {
  const t = text.toLowerCase();
  let s = 0;
  if (/\btrois quarts? d['’ ]?heure\b/.test(t)) s += 2700;
  else if (/\b(un )?quart d['’ ]?heure\b/.test(t)) s += 900;
  if (/\b(une )?demi[- ]heure\b/.test(t)) s += 1800;
  for (const m of t.matchAll(UNIT_RE)) {
    const n = num(m[1]), u = m[2];
    if (!Number.isFinite(n)) continue;
    if (u.startsWith("h")) s += n * 3600 + (m[3] ? Number(m[3]) * 60 : 0);
    else if (u.startsWith("m")) s += n * 60 + (m[3] ? Number(m[3]) : 0);
    else s += n;
  }
  if (s > 0 && /\bheures?\s+et\s+demie\b/.test(t)) s += 1800;
  return Math.round(s);
}

/** Libellé du minuteur : ce qui suit la durée (« … de vérifier l'enduit », « … pour la colle »). */
function labelOf(text: string): string {
  const last = [...text.matchAll(UNIT_RE)].pop();
  const rest = last ? text.slice((last.index ?? 0) + last[0].length) : "";
  const l = rest.replace(/^[\s,.:;-]*(?:et\s+demie\s*)?[\s,]*(?:(?:rappelle|pr[ée]viens|avertis|r[ée]veille)[- ]?moi\s+)?(?:de\s+|d['’]\s*|pour\s+|que\s+|qu['’]\s*)?/i, "").replace(/[\s.!?]+$/, "").trim();
  return l.slice(0, 80);
}

/** Phrase du patron → commande de minuteur, ou null (la phrase part à l'IA comme d'habitude). */
export function parseTimer(text: string): TimerCmd | null {
  const t = (text || "").trim();
  if (!t) return null;
  if (CANCEL_RE.test(t)) return { action: "cancel" };
  if (LIST_RE.test(t) && ASK_RE.test(t) && !duration(t)) return { action: "list" };
  if (!START_RE.test(t)) return null;
  const seconds = duration(t);
  if (seconds < 5 || seconds > MAX_S) return null;   // « rappelle-moi dans 2 jours » : l'agenda s'en charge (serveur)
  return { action: "start", seconds, label: labelOf(t) };
}

/** « 1 heure 30 », « 20 minutes », « 45 secondes » (à dire à voix haute). */
export function spoken(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h) return `${h} heure${h > 1 ? "s" : ""}${m ? ` ${m}` : ""}`;
  if (m) return `${m} minute${m > 1 ? "s" : ""}${r && m < 5 ? ` ${r}` : ""}`;
  return `${r} seconde${r > 1 ? "s" : ""}`;
}

const hour = (ms: number): string => { const d = new Date(ms); return `${d.getHours()} h ${String(d.getMinutes()).padStart(2, "0")}`; };

export function load(now = Date.now()): Timer[] {
  try { return (JSON.parse(localStorage.getItem(KEY) || "[]") as Timer[]).filter((x) => x && x.end > now); } catch { return []; }
}
function save(list: Timer[]): void { try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* ignoré */ } }

const webTimers = new Map<number, ReturnType<typeof setTimeout>>();

/** Exécute la commande et rend la phrase que UniC dit. `ring` : sonnerie du navigateur (hors téléphone). */
export async function runTimer(cmd: TimerCmd, ring: (label: string) => void, now = Date.now()): Promise<string> {
  const list = load(now);
  if (cmd.action === "list") {
    if (!list.length) return "Aucun minuteur en cours.";
    return list.sort((a, b) => a.end - b.end).map((x) => `Il reste ${spoken((x.end - now) / 1000)}${x.label ? ` pour ${x.label}` : ""}.`).join(" ");
  }
  if (cmd.action === "cancel") {
    if (!list.length) return "Aucun minuteur à annuler.";
    if (isNative) {
      const { LocalNotifications } = await import("@capacitor/local-notifications");
      await LocalNotifications.cancel({ notifications: list.map((x) => ({ id: x.id })) }).catch(() => {});
    }
    list.forEach((x) => { clearTimeout(webTimers.get(x.id)); webTimers.delete(x.id); });
    save([]);
    return list.length > 1 ? `${list.length} minuteurs annulés.` : "Minuteur annulé.";
  }
  const used = new Set(list.map((x) => x.id));
  const id = Array.from({ length: 100 }, (_, i) => BASE + i).find((i) => !used.has(i)) ?? BASE;
  const timer: Timer = { id, end: now + cmd.seconds * 1000, label: cmd.label };
  if (isNative) {
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    const perm = await LocalNotifications.requestPermissions();
    if (perm.display !== "granted") return "Notifications refusées : autorise-les dans Réglages, Applis, UniC AI, pour que le minuteur sonne.";
    await LocalNotifications.schedule({ notifications: [{
      id, title: "⏱️ Minuteur terminé", body: cmd.label || `Minuteur de ${spoken(cmd.seconds)}`,
      schedule: { at: new Date(timer.end), allowWhileIdle: true }, extra: { action: "timer" },
    }] });
  } else {
    webTimers.set(id, setTimeout(() => { webTimers.delete(id); save(load().filter((x) => x.id !== id)); ring(cmd.label); }, cmd.seconds * 1000));
  }
  save([...list, timer]);
  return `C'est parti : minuteur de ${spoken(cmd.seconds)}${cmd.label ? ` pour ${cmd.label}` : ""}. Je sonne à ${hour(timer.end)}.`
    + (isNative ? "" : " Garde la page ouverte.");
}
