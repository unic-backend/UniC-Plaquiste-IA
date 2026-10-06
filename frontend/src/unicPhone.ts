import { matchContacts, pickAmong, yesNo, type Contact } from "./phoneMatch";

/** Déroulé d'un appel ou d'un SMS demandé à voix haute. Rien ne part sans le « oui » entendu juste avant.
 *  Les dépendances sont injectées (voix, écoute, téléphone) : le même code marche dans l'appli et dans les tests. */
export type Intent = { action: "call" | "sms"; name: string; number: string; message: string };
export type Deps = {
  say: (t: string) => Promise<void>;
  listen: () => Promise<string>;
  phone: { listContacts: () => Promise<Contact[]>; call: (n: string) => Promise<void>; sendSms: (n: string, t: string) => Promise<void> };
  polish: (t: string) => Promise<string>;
};

async function confirm(d: Deps, question: string): Promise<boolean> {
  for (let i = 0; i < 2; i++) {
    await d.say(i === 0 ? question : "Réponds par oui ou par non.");
    const a = yesNo(await d.listen());
    if (a !== "unclear") return a === "yes";
  }
  await d.say("Je n'ai pas compris, j'annule.");
  return false;
}

export async function runPhoneIntent(it: Intent, d: Deps): Promise<void> {
  let number = it.number, label = it.number ? "ce numéro" : it.name;
  if (!number) {
    const cands = matchContacts(await d.phone.listContacts(), it.name);
    if (!cands.length) { await d.say(`Je ne trouve personne qui ressemble à ${it.name} dans tes contacts.`); return; }
    let pick = cands[0];
    if (cands.length > 1 && cands[0].score - cands[1].score < 0.08) {
      await d.say(`Tu veux dire ${cands[0].name} ou ${cands[1].name} ?`);
      const chosen = pickAmong(cands.slice(0, 2), await d.listen());
      if (!chosen) { await d.say("Je n'ai pas compris, j'annule."); return; }
      pick = chosen;
    }
    number = pick.number; label = pick.name;
  }
  if (it.action === "call") {
    if (await confirm(d, `J'appelle ${label}. Tu confirmes ?`)) { await d.phone.call(number); await d.say("Je lance l'appel."); }
    else await d.say("D'accord, j'annule.");
    return;
  }
  let msg = it.message.trim();
  if (!msg) {
    await d.say(`Qu'est-ce que je dis à ${label} ?`);
    msg = (await d.listen()).trim();
    if (!msg) { await d.say("Je n'ai rien entendu, j'annule."); return; }
  }
  const text = (await d.polish(msg)) || msg;
  if (await confirm(d, `J'envoie à ${label} : ${text}. Je confirme ?`)) { await d.phone.sendSms(number, text); await d.say("C'est envoyé."); }
  else await d.say("D'accord, je n'envoie rien.");
}
