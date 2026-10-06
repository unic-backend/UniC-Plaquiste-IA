/** Retrouver un contact à partir d'un nom dit à voix haute : tolère les fautes et les mots déformés par l'accent.
 *  Tout se passe sur le téléphone : les contacts ne partent nulle part. */
export type Contact = { name: string; number: string };
export type Match = Contact & { score: number };

const TITLES = new Set(["madame", "monsieur", "mme", "mr", "m", "mlle", "tonton", "tata", "papa", "maman", "le", "la", "chez", "mon", "ma"]);

export const fold = (s: string): string =>
  (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

/** Clé phonétique française simple : « Diallo » ≈ « Dialo », « Fall » ≈ « Fal », « Ousmane » ≈ « Usman ». */
export function phon(word: string): string {
  let x = fold(word);
  const rules: [RegExp, string][] = [
    [/ph/g, "f"], [/ch/g, "s"], [/dj|dg/g, "j"], [/gu(?=[ei])/g, "g"], [/qu|ck|k/g, "k"], [/c(?=[aou])/g, "k"], [/c/g, "s"],
    [/eau|au/g, "o"], [/ou/g, "u"], [/ai|ei|et$/g, "e"], [/y/g, "i"], [/w/g, "u"], [/h/g, ""], [/z/g, "s"],
    [/(.)\1+/g, "$1"], [/[sxtd]$/, ""], [/[eé]$/, ""],
  ];
  for (const [re, to] of rules) x = x.replace(re, to);
  return x;
}

export function lev(a: string, b: string): number {
  const m = a.length, n = b.length;
  if (!m) return n;
  if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[n];
}

const tokens = (s: string): string[] => fold(s).split(" ").filter((w) => w && !TITLES.has(w));

function tokenSim(q: string, c: string): number {
  if (!q || !c) return 0;
  const exact = fold(q) === fold(c) ? 1 : 0;
  const pq = phon(q), pc = phon(c);
  const ph = pq && pc ? 1 - lev(pq, pc) / Math.max(pq.length, pc.length) : 0;
  const raw = 1 - lev(fold(q), fold(c)) / Math.max(q.length, c.length);
  return Math.max(exact, ph, raw * 0.95);
}

/** Contacts classés du plus ressemblant au moins ressemblant (score entre 0 et 1, seuil 0,72). */
export function matchContacts(contacts: Contact[], spoken: string): Match[] {
  const q = tokens(spoken);
  if (!q.length) return [];
  const byName = new Map<string, Match>();
  for (const c of contacts) {
    const ct = tokens(c.name);
    if (!ct.length) continue;
    const best = q.map((w) => Math.max(...ct.map((t) => tokenSim(w, t))));
    const score = best.reduce((a, b) => a + b, 0) / q.length;
    const cur = byName.get(fold(c.name));
    if (score >= 0.72 && (!cur || score > cur.score)) byName.set(fold(c.name), { ...c, score });
  }
  return [...byName.values()].sort((a, b) => b.score - a.score).slice(0, 5);
}

/** « Awa Fall ou Awa Diop » : le patron répond « Diop » → le candidat choisi (ou null). */
export function pickAmong(cands: Match[], answer: string): Match | null {
  const hit = matchContacts(cands, answer);
  if (hit.length && (hit.length === 1 || hit[0].score - hit[1].score >= 0.08)) return cands.find((c) => c.name === hit[0].name) || null;
  if (/\b(premier|le premier|1er)\b/i.test(answer)) return cands[0];
  if (/\b(deuxi[eè]me|second|le second|2e)\b/i.test(answer)) return cands[1] || null;
  return null;
}

export type Answer = "yes" | "no" | "unclear";
export function yesNo(heard: string): Answer {
  const t = fold(heard);
  if (/^(non|no|nan|annule|annuler|stop|laisse|laisse tomber|pas maintenant|arrete|jamais|surtout pas)\b/.test(t)) return "no";
  if (/^(oui|ouais|ouai|wi|yes|ok|okay|d accord|dac|vas y|va y|go|confirme|confirmer|envoie|appelle|c est bon|exactement|tout a fait|bien sur|parfait|allez)\b/.test(t)) return "yes";
  return "unclear";
}
