// Vérifie la parole au fil de l'eau (phrases dites dès qu'elles sont complètes) et le tri des demandes de téléphone. Lancer : npm run test:phone
import { SpeechPipeline, takeSentences } from "../src/sentences";
import { looksLikePhoneTask } from "../src/notifs";

let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };

// découpage en phrases
eq("deux phrases", takeSentences("Bonjour patron, je m'en occupe tout de suite. Le devis est prêt pour toi. Et").ready,
  ["Bonjour patron, je m'en occupe tout de suite.", "Le devis est prêt pour toi."]);
eq("reste en attente", takeSentences("Bonjour patron, je m'en occupe tout de suite. Le devis est").rest, "Le devis est");
eq("décimale ne coupe pas", takeSentences("Il te faut 3.5 mètres carrés de plaques pour le plafond. OK").ready, ["Il te faut 3.5 mètres carrés de plaques pour le plafond."]);
eq("phrase trop courte regroupée", takeSentences("Oui. Je regarde ça tout de suite pour toi. ").ready, ["Oui. Je regarde ça tout de suite pour toi."]);
eq("rien de complet", takeSentences("Je cherche").ready, []);

// pipeline : chaque phrase est envoyée AU MOTEUR tout de suite (il les enchaîne sans temps mort), dans l'ordre
async function pipe() {
  const log: string[] = [];
  let chain: Promise<void> = Promise.resolve();   // le moteur de voix : file d'attente interne
  const engine = (t: string) => { log.push("envoyé:" + t); chain = chain.then(async () => { log.push("dit:" + t); await new Promise((r) => setTimeout(r, 20)); }); return chain; };
  const p = new SpeechPipeline(engine, () => log.push("stop"));
  p.push("Bonjour patron, je m'en occupe tout de suite. ");
  p.push("Le devis est prêt pour toi, il fait cent cinquante mille francs. ");
  log.push("encore en train d'écrire…");
  p.push("Dernière phrase pour finir la réponse.");
  await p.finish();
  eq("1re phrase envoyée avant la fin de la réponse", log.indexOf("envoyé:Bonjour patron, je m'en occupe tout de suite.") < log.indexOf("encore en train d'écrire…"), true);
  eq("2e phrase envoyée sans attendre la fin de la 1re", log.indexOf("envoyé:Le devis est prêt pour toi, il fait cent cinquante mille francs.") < log.indexOf("dit:Bonjour patron, je m'en occupe tout de suite.") + 3, true);
  eq("ordre de lecture", log.filter((x) => x.startsWith("dit:")).map((x) => x.slice(4)),
    ["Bonjour patron, je m'en occupe tout de suite.", "Le devis est prêt pour toi, il fait cent cinquante mille francs.", "Dernière phrase pour finir la réponse."]);
  const log2: string[] = [];
  const q = new SpeechPipeline(async (t) => { log2.push(t); }, () => log2.push("stop"));
  q.push("Une première phrase assez longue pour partir tout de suite. Suite");
  q.cancel(); q.push("Après annulation, rien ne doit plus être dit du tout. "); await q.finish();
  eq("annulation : plus rien", log2.filter((x) => x !== "stop").length <= 1 && log2.includes("stop"), true);
}
await pipe();

// tri des demandes : seules celles qui parlent d'appel ou de message vont au serveur
for (const [s, w] of [["appelle Awa", true], ["apèle Moussa", true], ["envoie un message à Awa", true], ["écris à papa", true], ["dis à Ibou que je viens", true], ["prévenir Ibrahima", true], ["envoi un sms", true],
  ["fais le devis de madame Diop", false], ["quel temps fait-il", false], ["combien de plaques pour 134 mètres carrés", false], ["bonjour UniC", false], ["qu'est-ce que tu sais faire", false]] as const)
  eq("téléphone ? " + s, looksLikePhoneTask(s), w);
console.log(`OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
