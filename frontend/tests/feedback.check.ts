// Vérifie le retour immédiat au toucher : activité réseau, notices, garde anti double-appui. Lancer : npm run test:phone
import { DOUBLE_TAP_MS, isDoubleTap, netNote, netSnapshot, netStart, notify, noticeSnapshot, subscribeNet, subscribeNotice } from "../src/feedback";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };

// garde anti double-appui : même bouton + moins de 350 ms = ignoré ; autre bouton ou plus tard = accepté
const A = {}, B = {};
eq("premier appui accepté", isDoubleTap(null, A, 1000), false);
eq("même bouton à 100 ms : ignoré", isDoubleTap({ el: A, t: 1000 }, A, 1100), true);
eq("même bouton à 349 ms : ignoré", isDoubleTap({ el: A, t: 1000 }, A, 1000 + DOUBLE_TAP_MS - 1), true);
eq("même bouton à 350 ms : accepté", isDoubleTap({ el: A, t: 1000 }, A, 1000 + DOUBLE_TAP_MS), false);
eq("autre bouton aussitôt : accepté", isDoubleTap({ el: A, t: 1000 }, B, 1010), false);

// l'instantané doit garder la MÊME identité tant que rien ne change (sinon boucle de rendu infinie dans React)
eq("instantané stable sans changement", netSnapshot() === netSnapshot(), true);
// activité réseau : compteur, idempotence, retour à zéro, note effacée
eq("rien au départ", netSnapshot().pending, 0);
let calls = 0; const off = subscribeNet(() => { calls++; });
const snap0 = netSnapshot();
const e1 = netStart(), e2 = netStart();
eq("l'instantané change quand l'état change", netSnapshot() !== snap0, true);
const snap2 = netSnapshot(); eq("et reste identique ensuite", netSnapshot() === snap2, true);
eq("2 requêtes en cours", netSnapshot().pending, 2);
eq("l'heure de début est posée", netSnapshot().since > 0, true);
netNote("Connexion au serveur…");
eq("note visible", netSnapshot().note, "Connexion au serveur…");
e1(); e1();                                         // fin appelée deux fois : ne compte qu'une fois
eq("fin idempotente", netSnapshot().pending, 1);
e2();
eq("retour à zéro", netSnapshot().pending, 0);
eq("note effacée à la fin", netSnapshot().note, "");
eq("les abonnés sont prévenus", calls >= 4, true);
off();
const before = calls; netStart()(); eq("désabonné : plus d'appel", calls, before);

// notice globale
let n = 0; const offN = subscribeNotice(() => { n++; });
notify("✓ Enregistré", 5);
eq("notice affichée", noticeSnapshot(), "✓ Enregistré");
await new Promise((r) => setTimeout(r, 40));
eq("notice effacée seule", noticeSnapshot(), "");
eq("abonnés prévenus (affiche + efface)", n, 2);
offN();
console.log(`OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
