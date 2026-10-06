import { fold, lev, phon } from "./phoneMatch";

/** « Qu'est-ce que j'ai reçu ? » et « lis-moi le message » : tout est calculé sur le téléphone, rien n'est envoyé au serveur. */
export type Notif = { id: string; pkg: string; app: string; title: string; text: string; category: string; time: number; removed: boolean };
export type Command = { kind: "list" | "read" | "next" | "none"; app: string; who: string; which: "last" | "first" | "all" };

const MESSAGING = /whatsapp|messenger|telegram|signal|viber|messag|sms|mms|chat|discord|wechat|line|imo|snapchat/i;
const SMS_PKG = /(messaging|mms|sms|telephony|conversations|messenger\.sms)/i;
const ALIASES: Record<string, RegExp> = {
  whatsapp: /whatsapp/i, watsap: /whatsapp/i, wazap: /whatsapp/i, ouatsap: /whatsapp/i, instagram: /instagram/i, insta: /instagram/i,
  facebook: /facebook\.katana|facebook(?!.*messenger)/i, face: /facebook\.katana/i, messenger: /messenger|facebook\.orca/i,
  reddit: /reddit/i, telegram: /telegram/i, tiktok: /tiktok|musically/i, snapchat: /snapchat/i, gmail: /gmail|google\.android\.gm/i,
  mail: /gmail|mail/i, linkedin: /linkedin/i, twitter: /twitter|x\.android/i, youtube: /youtube/i, sms: SMS_PKG, texto: SMS_PKG,
};

const GENERIC = new Set(["messages", "message", "notification", "notifications", "notif", "message(s)"]);   // mots de la demande, pas des noms d'applis
const sim = (a: string, b: string): number => {
  const pa = phon(a), pb = phon(b);
  const p = pa && pb ? 1 - lev(pa, pb) / Math.max(pa.length, pb.length) : 0;
  const r = a && b ? 1 - lev(fold(a), fold(b)) / Math.max(a.length, b.length) : 0;
  return Math.max(p, r * 0.95);
};
const hasWord = (words: string[], target: string, thr = 0.8): boolean => words.some((w) => w.length > 2 && sim(w, target) >= thr);

export const isMessage = (n: Notif): boolean => n.category === "msg" || MESSAGING.test(n.app) || MESSAGING.test(n.pkg);
export const isSms = (n: Notif): boolean => SMS_PKG.test(n.pkg) || /^(messages?|sms)$/i.test(n.app.trim());
export const appName = (n: Notif): string => (isSms(n) ? "SMS" : n.app);

/** Type de demande, sans avoir besoin de la liste (le téléphone la charge seulement ensuite). */
export function quickKind(heard: string): "list" | "read" | "next" | "none" {
  const t = fold(heard);
  const words = t.split(" ").filter(Boolean);
  if (!words.length) return "none";
  if (/^(suivant|le suivant|encore|apres|continue|la suite|prochain|le prochain|et apres)\b/.test(t)) return "next";
  const verb = ["lis", "lire", "lit", "li", "lise", "lisez", "lecture", "ecoute", "ecouter"].includes(words[0]) || sim(words[0], "lire") >= 0.85
    || /^(dis moi|dit moi|donne moi)\b/.test(t) || /^(je veux|peux tu|tu peux|veux tu)\s+(lire|lis|ecouter|entendre)/.test(t);
  const target = hasWord(words, "message") || hasWord(words, "notification") || hasWord(words, "notif") || /\b(whatsapp|watsap|sms|texto|instagram|insta|facebook|messenger|reddit|telegram|dernier|premier|tout|tous|mail|gmail)\b/.test(t);
  if (verb && target) return "read";
  const asks = /\b(recu|recois|recevoir|nouveau|nouveaux|nouvelle|nouvelles)\b/.test(t) || hasWord(words, "notification") || hasWord(words, "notif")
    || /\bqui (m a|ma|m as) (ecrit|envoye|appele)\b/.test(t) || /\bj ai quoi\b/.test(t);
  if (asks && !verb) return "list";
  return "none";
}

/** Précise la demande avec ce que contient le téléphone : quelle appli, de qui, lequel. */
export function parseCommand(heard: string, items: Notif[]): Command {
  const t = fold(heard), words = t.split(" ").filter(Boolean);
  const kind = quickKind(heard);
  let app = "";
  for (const [alias, re] of Object.entries(ALIASES)) if (hasWord(words, alias, 0.84) && items.some((n) => re.test(n.pkg) || re.test(n.app))) { app = alias; break; }
  if (!app) for (const n of items) for (const w of fold(n.app).split(" ")) if (w.length > 3 && !GENERIC.has(w) && hasWord(words, w, 0.85)) { app = fold(n.app); break; }
  const m = t.match(/\b(?:de|du|d|from)\s+([a-z0-9 ]{2,30})$/);
  let who = m ? m[1].trim() : "";
  if (who && Object.keys(ALIASES).some((a) => sim(who, a) >= 0.85)) who = "";
  const which = /\b(premier|premiere|plus ancien|ancien)\b/.test(t) ? "first" : /\b(tout|tous|toutes|les messages|mes messages|les notifications)\b/.test(t) ? "all" : "last";
  return { kind, app, who, which };
}

export function select(items: Notif[], cmd: Command): Notif[] {
  let list = items.filter((n) => !n.removed).sort((a, b) => b.time - a.time);
  if (cmd.app) {
    const re = ALIASES[cmd.app];
    list = list.filter((n) => (re ? re.test(n.pkg) || re.test(n.app) : fold(n.app).includes(cmd.app)));
  } else if (list.some(isMessage)) list = list.filter(isMessage);
  if (cmd.who) {
    const q = fold(cmd.who).split(" ").filter(Boolean);
    const score = (n: Notif) => q.reduce((s, w) => s + Math.max(0, ...fold(n.title).split(" ").map((t) => sim(w, t))), 0) / q.length;
    list = list.filter((n) => score(n) >= 0.75);
  }
  if (cmd.which === "first") list = [...list].reverse();
  return list;
}

const clip = (s: string, n = 400): string => (s.length > n ? s.slice(0, n) + "…" : s);

export function describe(items: Notif[]): string {
  const live = items.filter((n) => !n.removed);
  if (!live.length) return "Tu n'as aucune notification.";
  const groups = new Map<string, Notif[]>();
  for (const n of live) groups.set(appName(n), [...(groups.get(appName(n)) || []), n]);
  const parts = [...groups.entries()].slice(0, 6).map(([app, list]) => {
    const msg = isMessage(list[0]);
    const noun = msg ? (list.length > 1 ? "messages" : "message") : list.length > 1 ? "notifications" : "notification";
    const who = msg && list.length <= 3 ? [...new Set(list.map((n) => n.title).filter(Boolean))].slice(0, 3) : [];
    return `${list.length} ${noun} ${app === "SMS" ? "SMS" : app}${who.length ? ", de " + who.join(" et de ") : ""}`;
  });
  const more = groups.size > 6 ? " et d'autres" : "";
  return `Tu as ${live.length} notification${live.length > 1 ? "s" : ""} : ${parts.join(", ")}${more}. Dis « lis le dernier message » pour l'entendre.`;
}

export function readSentence(n: Notif): string {
  const app = appName(n);
  if (isMessage(n)) return `${app}${n.title ? ", de " + n.title : ""} : ${clip(n.text || "message sans texte")}`;
  return `${app} : ${[n.title, clip(n.text)].filter(Boolean).join(". ")}`;
}

export type NDeps = {
  say: (t: string) => Promise<void>;
  api: { list: () => Promise<Notif[]>; enabled: () => Promise<boolean>; openSettings: () => Promise<void>; locked: () => Promise<boolean> };
  readWhenLocked: boolean;
  queue: { items: Notif[]; index: number };
};

/** Rend vrai si la demande était une demande de notifications (traitée ici), faux sinon. */
export async function runNotifCommand(heard: string, d: NDeps): Promise<boolean> {
  const kind = quickKind(heard);
  if (kind === "none") return false;
  if (kind === "next") {
    if (d.queue.index + 1 >= d.queue.items.length) return false;   // rien en cours : ce n'est pas pour nous
    d.queue.index += 1;
    await d.say(readSentence(d.queue.items[d.queue.index]));
    if (d.queue.index + 1 < d.queue.items.length) await d.say("Dis suivant pour le suivant.");
    return true;
  }
  if (!(await d.api.enabled())) {
    await d.say("Je n'ai pas accès à tes notifications. Ouvre les réglages « Accès aux notifications » et active UniC AI. Je les ouvre maintenant.");
    await d.api.openSettings();
    return true;
  }
  if ((await d.api.locked()) && !d.readWhenLocked) {
    await d.say("Ton téléphone est verrouillé : déverrouille-le pour que je lise tes notifications.");
    return true;
  }
  const items = await d.api.list();
  if (kind === "list") { await d.say(describe(items)); return true; }
  const cmd = parseCommand(heard, items);
  const picked = select(items, cmd);
  if (!picked.length) { await d.say(cmd.who || cmd.app ? "Je ne trouve pas de message correspondant." : "Tu n'as aucun message à lire."); return true; }
  const take = cmd.which === "all" ? picked.slice(0, 5) : picked.slice(0, 1);
  d.queue.items = take; d.queue.index = 0;
  if (cmd.which !== "all" && picked.length > 1) { d.queue.items = picked.slice(0, 5); }
  await d.say(readSentence(d.queue.items[0]));
  if (d.queue.items.length > 1) await d.say("Dis suivant pour le suivant.");
  return true;
}
