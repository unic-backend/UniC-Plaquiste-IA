// Minuteurs à la voix et suite de phrase (idées reprises de ming-voice). Lancer : npm run test:phone
import { duration, parseTimer, spoken } from "../src/timers";
import { END_RE, isContinuation, wholeSentence } from "../src/unicPhone";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };

// durées dites
for (const [s, d] of [["20 minutes", 1200], ["1 h 30", 5400], ["1h30", 5400], ["2 heures", 7200], ["une heure et demie", 5400], ["une demi-heure", 1800],
  ["un quart d'heure", 900], ["trois quarts d'heure", 2700], ["vingt minutes", 1200], ["vingt-cinq minutes", 1500], ["90 secondes", 90], ["45 s", 45],
  ["1 heure 30 minutes", 5400], ["2 min 30", 150], ["2,5 minutes", 150], ["aucune heure", 0], ["pose 20 m²", 0]] as const) eq("durée " + s, duration(s), d);

// commandes
eq("minuteur simple", parseTimer("Mets un minuteur de 20 minutes"), { action: "start", seconds: 1200, label: "" });
eq("minuteur + libellé", parseTimer("minuteur 45 minutes pour la colle"), { action: "start", seconds: 2700, label: "la colle" });
eq("rappelle-moi dans", parseTimer("Rappelle-moi dans 10 minutes de vérifier l'enduit"), { action: "start", seconds: 600, label: "vérifier l'enduit" });
eq("dans … rappelle-moi", parseTimer("dans 15 minutes rappelle-moi de sortir les plaques"), { action: "start", seconds: 900, label: "sortir les plaques" });
eq("chrono 1h30", parseTimer("lance un chrono de 1h30"), { action: "start", seconds: 5400, label: "" });
eq("annule", parseTimer("annule le minuteur"), { action: "cancel" });
eq("arrête", parseTimer("arrête les minuteurs"), { action: "cancel" });
eq("combien reste", parseTimer("combien de temps il reste au minuteur ?"), { action: "list" });
eq("où en est", parseTimer("où en est le chrono"), { action: "list" });
// ce qui n'est PAS un minuteur part à l'IA (agenda, devis, appels…)
for (const s of ["rappelle-moi demain à 9 h d'appeler Diop", "rappelle-moi dans 2 jours", "fais le devis de 20 m²", "minuteur", "combien de temps pour poser 30 m² ?",
  "coupe l'appel", "stop", "", "mets un minuteur de 2 secondes", "minuteur de 30 heures"]) eq("pas un minuteur : " + s, parseTimer(s), null);

// à voix haute
for (const [n, t] of [[1200, "20 minutes"], [5400, "1 heure 30"], [7200, "2 heures"], [45, "45 secondes"], [150, "2 minutes 30"], [61, "1 minute 1"], [600.4, "10 minutes"]] as const)
  eq("dit " + n, spoken(n), t);

// suite de phrase : un bruit ou un « euh » ne coupe pas la réponse ; deux mots, si
for (const [s, c] of [["euh", false], ["Euh...", false], ["ok", false], ["d'accord", false], ["", false], ["et la cuisine", true], ["salon", true],
  ["avec 20 m² au salon", true], ["non", false]] as const) eq("suite " + s, isContinuation(s), c);
eq("phrase entière", wholeSentence("fais un devis pour Diop ", " de 20 m² au salon"),
  "Je reprends ma phrase en entier (ta réponse précédente n'a pas été lue) : fais un devis pour Diop de 20 m² au salon");
eq("« stop » en continuant = fin", END_RE.test("stop"), true);

console.log(`minuteurs : ${ok} OK, ${ko} échec(s)`);
if (ko) process.exit(1);
