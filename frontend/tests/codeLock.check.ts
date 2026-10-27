// Vérifie le code de l'appli : empreinte seule, essais faux freinés, délai de retour. Lancer : npm run test:phone
import * as lock from "../src/codeLock";

let ok = 0, ko = 0;
const eq = (label: string, got: unknown, want: unknown) => { const g = JSON.stringify(got), w = JSON.stringify(want); (g === w ? ok++ : ko++); if (g !== w) console.log("ÉCHEC", label, g, "≠", w); };
const mem = new Map<string, string>();
const s = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => { mem.set(k, v); }, removeItem: (k: string) => { mem.delete(k); } };

(async () => {
  for (const [p, w] of [["1234", true], ["12345678", true], ["123", false], ["123456789", false], ["12a4", false], ["", false]] as const) eq("validPin " + p, lock.validPin(p), w);
  eq("coupé par défaut", lock.enabled(s), false);
  eq("sans code : ouvert", (await lock.check("0000", 0, s)).ok, true);
  let threw = false;
  try { await lock.setPin("12", 0, s); } catch { threw = true; }
  eq("code trop court refusé", threw && !lock.enabled(s), true);

  await lock.setPin("2580", 60_000, s);
  const saved = mem.get("unic.applock") || "";
  eq("activé", lock.enabled(s), true);
  eq("le code n'est jamais gardé", saved.includes("2580"), false);
  eq("longueur et délai gardés", [lock.config(s)?.len, lock.config(s)?.idleMs], [4, 60_000]);
  eq("bon code", await lock.check("2580", 0, s), { ok: true, waitMs: 0 });

  const t0 = 1_000_000;
  for (let i = 1; i < lock.FREE_TRIES; i++) eq(`faux ${i} : pas d'attente`, await lock.check("0000", t0, s), { ok: false, waitMs: 0 });
  eq("5e faux : 30 s", await lock.check("0000", t0, s), { ok: false, waitMs: 30_000 });
  eq("bon code pendant l'attente : refusé", (await lock.check("2580", t0 + 10_000, s)).ok, false);
  eq("6e faux après l'attente : 60 s", await lock.check("0000", t0 + 31_000, s), { ok: false, waitMs: 60_000 });
  eq("attente restante", lock.waitMs(t0 + 61_000, s), 30_000);
  eq("bon code après l'attente", (await lock.check("2580", t0 + 200_000, s)).ok, true);
  eq("compteur remis à zéro", lock.waitMs(t0 + 200_000, s), 0);
  for (let i = 0; i < 20; i++) await lock.check("1111", t0 + 10 ** 9 * (i + 1), s);
  eq("attente plafonnée à 15 min", lock.waitMs(t0 + 10 ** 9 * 20, s), 15 * 60_000);

  lock.setIdle(0, s);
  eq("délai changé, code gardé", [lock.config(s)?.idleMs, lock.enabled(s)], [0, true]);
  eq("retour après 1 min (délai 1 min)", lock.dueAfter(0, 60_000, 60_000), true);
  eq("retour après 30 s (délai 1 min)", lock.dueAfter(0, 30_000, 60_000), false);
  eq("pas parti", lock.dueAfter(null, 10 ** 9, 0), false);
  lock.clear(s);
  eq("retiré", [lock.enabled(s), mem.size], [false, 0]);

  console.log(`codeLock : OK ${ok}  ÉCHECS ${ko}`);
  if (ko) process.exit(1);
})();
