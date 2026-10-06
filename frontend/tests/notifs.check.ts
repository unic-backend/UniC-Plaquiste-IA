// Vérifie « qu'est-ce que j'ai reçu » et « lis-moi le message » (fautes de prononciation, filtres, téléphone verrouillé). Lancer : npm run test:phone
import { quickKind, parseCommand, select, describe, readSentence, runNotifCommand, type Notif } from "../src/notifs";
const now = Date.now();
const N = (id: string, pkg: string, app: string, title: string, text: string, ageMin: number, category = "msg"): Notif => ({ id, pkg, app, title, text, category, time: now - ageMin * 60000, removed: false });
const items: Notif[] = [
  N("1", "com.whatsapp", "WhatsApp", "Awa Fall", "Je suis devant le chantier", 2),
  N("2", "com.whatsapp", "WhatsApp", "Moussa Ndiaye", "Tu peux m'appeler ?", 9),
  N("3", "com.samsung.android.messaging", "Messages", "Papa", "Bonne nuit", 30),
  N("4", "com.instagram.android", "Instagram", "Instagram", "ibou_style a aimé votre photo", 5, "social"),
  N("5", "com.reddit.frontpage", "Reddit", "r/btp", "Nouveau post populaire", 40, "social"),
];
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };
// reconnaissance de la demande (fautes comprises)
for (const [s, k] of [["Qu'est-ce que j'ai reçu comme notification", "list"], ["kes ke jai resu come notifikasion", "list"], ["qui m'a écrit", "list"], ["j'ai des nouveaux messages", "list"],
  ["lis-moi le message", "read"], ["lis moi le dernier message de Awa", "read"], ["lire le message whatsapp", "read"], ["li le mesage", "read"], ["je veux écouter mon message", "read"],
  ["suivant", "next"], ["envoie un message à Awa", "none"], ["fais le devis de madame Diop", "none"], ["appelle Moussa", "none"], ["bonjour", "none"]] as const) eq("kind " + s, quickKind(s), k);
// filtres
let c = parseCommand("lis moi le message de Moussa", items); eq("who Moussa", select(items, c)[0]?.id, "2");
c = parseCommand("lis le message whatsapp", items); eq("whatsapp = Awa (le plus récent)", select(items, c)[0]?.id, "1");
c = parseCommand("lis moi le message instagram", items); eq("instagram", select(items, c)[0]?.id, "4");
c = parseCommand("lis le message de Awa Fal", items); eq("Awa mal dit", select(items, c)[0]?.id, "1");
c = parseCommand("lis le dernier message", items); eq("dernier = plus récent des messages", select(items, c)[0]?.id, "1");
c = parseCommand("lis le premier message", items); eq("premier = plus ancien message", select(items, c)[0]?.id, "3");
c = parseCommand("lis le message sms", items); eq("sms", select(items, c)[0]?.id, "3");
c = parseCommand("lis le message reddit", items); eq("reddit", select(items, c)[0]?.id, "5");
eq("describe", describe(items), "Tu as 5 notifications : 2 messages WhatsApp, de Awa Fall et de Moussa Ndiaye, 1 message SMS, de Papa, 1 notification Instagram, 1 notification Reddit. Dis « lis le dernier message » pour l'entendre.");
eq("aucune", describe([]), "Tu n'as aucune notification.");
eq("lecture message", readSentence(items[0]), "WhatsApp, de Awa Fall : Je suis devant le chantier");
eq("lecture autre appli", readSentence(items[3]), "Instagram : Instagram. ibou_style a aimé votre photo");
// déroulés
async function run(heard: string, o: { enabled?: boolean; locked?: boolean; readLocked?: boolean; list?: Notif[]; queue?: any } = {}) {
  const said: string[] = []; let opened = false;
  const queue = o.queue || { items: [], index: 0 };
  const handled = await runNotifCommand(heard, { say: async (t) => { said.push(t); }, readWhenLocked: o.readLocked ?? true, queue,
    api: { list: async () => o.list ?? items, enabled: async () => o.enabled ?? true, openSettings: async () => { opened = true; }, locked: async () => o.locked ?? false } });
  return { handled, said, opened, queue };
}
let r = await run("lis moi le message de Awa"); eq("lit Awa", [r.handled, r.said[0]], [true, "WhatsApp, de Awa Fall : Je suis devant le chantier"]);
r = await run("lis le message", { }); eq("annonce suivant", r.said[1], "Dis suivant pour le suivant.");
const q = r.queue; r = await run("suivant", { queue: q }); eq("suivant lit le 2e", r.said[0], "WhatsApp, de Moussa Ndiaye : Tu peux m'appeler ?");
r = await run("suivant", { queue: { items: [], index: 0 } }); eq("suivant sans file = pas pour nous", r.handled, false);
r = await run("qu'est-ce que j'ai reçu"); eq("liste dite", r.said[0].startsWith("Tu as 5 notifications"), true);
r = await run("qu'est-ce que j'ai reçu", { enabled: false }); eq("accès absent → réglages ouverts", [r.opened, r.said.length], [true, 1]);
r = await run("lis le message", { locked: true, readLocked: false }); eq("verrouillé et interdit", [r.said[0].startsWith("Ton téléphone est verrouillé"), r.said.length], [true, 1]);
r = await run("lis le message", { locked: true, readLocked: true }); eq("verrouillé mais autorisé", r.said[0].startsWith("WhatsApp"), true);
r = await run("lis le message de Zinedine"); eq("introuvable", r.said[0], "Je ne trouve pas de message correspondant.");
r = await run("lis le message", { list: [] }); eq("rien à lire", r.said[0], "Tu n'as aucun message à lire.");
r = await run("fais le devis"); eq("autre demande ignorée", r.handled, false);
console.log(`OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
