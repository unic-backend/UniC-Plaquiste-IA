// Vérifie la recherche de contacts (noms mal prononcés), le oui/non et les déroulés appel/SMS. Lancer : npm run test:phone
import { matchContacts, pickAmong, yesNo, phon } from "../src/phoneMatch";
import { runPhoneIntent } from "../src/unicPhone";
const contacts = [
  { name: "Awa Fall", number: "+221771111111" }, { name: "Awa Diop", number: "+221772222222" }, { name: "Moussa Ndiaye", number: "+221773333333" },
  { name: "Ousmane Diallo", number: "+221774444444" }, { name: "Madame Ribeiro", number: "+221775555555" }, { name: "Papa", number: "+221776666666" },
];
let ok = 0, ko = 0;
const eq = (label: string, got: unknown, want: unknown) => { const g = JSON.stringify(got), w = JSON.stringify(want); (g === w ? ok++ : ko++); if (g !== w) console.log("ÉCHEC", label, g, "≠", w); };
// noms mal prononcés
eq("Dialo → Diallo", matchContacts(contacts, "Dialo")[0]?.name, "Ousmane Diallo");
eq("Ribero → Ribeiro", matchContacts(contacts, "madame Ribero")[0]?.name, "Madame Ribeiro");
eq("Usman Dialo", matchContacts(contacts, "Usman Dialo")[0]?.name, "Ousmane Diallo");
eq("Mussa Ndiay", matchContacts(contacts, "Mussa Ndiay")[0]?.name, "Moussa Ndiaye");
eq("Awa Fal", matchContacts(contacts, "Awa Fal")[0]?.name, "Awa Fall");
eq("inconnu", matchContacts(contacts, "Zinedine").length, 0);
eq("Awa seul = 2 candidats", matchContacts(contacts, "Awa").map((m) => m.name).sort(), ["Awa Diop", "Awa Fall"]);
eq("pick Diop", pickAmong(matchContacts(contacts, "Awa"), "Diop")?.name, "Awa Diop");
eq("pick deuxième", pickAmong(matchContacts(contacts, "Awa").slice(0, 2), "le deuxième") !== null, true);
for (const [a, w] of [["oui", "yes"], ["Ouais vas-y", "yes"], ["d'accord", "yes"], ["non", "no"], ["annule", "no"], ["euh peut-être", "unclear"], ["", "unclear"]] as const) eq("yesNo " + a, yesNo(a), w);

// déroulés
let composerOnly = false;
async function run(intent: any, answers: string[]) {
  const said: string[] = [], actions: string[] = [];
  await runPhoneIntent(intent, {
    say: async (t) => { said.push(t); }, listen: async () => answers.shift() ?? "",
    phone: { listContacts: async () => contacts, call: async (n) => { actions.push("CALL " + n); }, sendSms: async (n, t) => { actions.push("SMS " + n + " | " + t); return composerOnly; } },
    polish: async (t) => t.replace("sui", "suis"),
  });
  return { said, actions };
}
let r = await run({ action: "call", name: "Dialo", number: "", message: "" }, ["oui"]);
eq("appel confirmé", r.actions, ["CALL +221774444444"]);
r = await run({ action: "call", name: "Dialo", number: "", message: "" }, ["non"]);
eq("appel refusé = rien", r.actions, []);
r = await run({ action: "call", name: "Dialo", number: "", message: "" }, ["bof", "hmm"]);
eq("réponse floue deux fois = rien", r.actions, []);
r = await run({ action: "sms", name: "Moussa", number: "", message: "je sui en retard" }, ["oui"]);
eq("sms corrigé + confirmé", r.actions, ["SMS +221773333333 | je suis en retard"]);
r = await run({ action: "sms", name: "Moussa", number: "", message: "" }, ["je passe demain", "oui"]);
eq("sms message demandé", r.actions, ["SMS +221773333333 | je passe demain"]);
r = await run({ action: "sms", name: "Awa", number: "", message: "salut" }, ["Fall", "oui"]);
eq("Awa ambiguë → Fall", r.actions, ["SMS +221771111111 | salut"]);
r = await run({ action: "sms", name: "Awa", number: "", message: "salut" }, ["euh", ]);
eq("ambiguïté non résolue = rien", r.actions, []);
r = await run({ action: "call", name: "Zinedine", number: "", message: "" }, []);
eq("contact inconnu = rien", r.actions, []);
r = await run({ action: "call", name: "", number: "777085092", message: "" }, ["oui"]);
eq("numéro dicté", r.actions, ["CALL 777085092"]);
r = await run({ action: "sms", name: "Moussa", number: "", message: "" }, [""]);
eq("silence = rien", r.actions, []);
r = await run({ action: "call", name: "", number: "", message: "" }, ["Dialo", "oui"]);
eq("appel sans nom : UniC demande, puis appelle", [r.said[0], r.actions], ["Qui veux-tu appeler ?", ["CALL +221774444444"]]);
r = await run({ action: "call", name: "", number: "", message: "" }, ["appelle Moussa", "oui"]);
eq("nom précédé de « appelle »", r.actions, ["CALL +221773333333"]);
r = await run({ action: "call", name: "", number: "", message: "" }, [""]);
eq("appel sans nom ni réponse = rien", r.actions, []);
r = await run({ action: "sms", name: "", number: "", message: "" }, ["Moussa", "je viens demain", "oui"]);
eq("sms sans nom : demande, puis message", [r.said[0], r.actions], ["À qui j'écris ?", ["SMS +221773333333 | je viens demain"]]);
composerOnly = true;
r = await run({ action: "sms", name: "Moussa", number: "", message: "je viens" }, ["oui"]);
eq("SMS bloqué par Android : plan B annoncé", r.said[r.said.length - 1].startsWith("Android bloque l'envoi direct"), true);
composerOnly = false;
console.log(`OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
