/** Salutations affichées à l'ouverture. Le Sénégal passe en premier (poids élevé).
 *  À corriger ici seulement : une langue absente = phrase non vérifiée, jamais inventée. */
export type Greeting = { lang: string; text: string; fr: string; weight: number };

export const GREETINGS: Greeting[] = [
  { lang: "Wolof", text: "Salaam maleekum", fr: "Que la paix soit sur vous", weight: 3 },
  { lang: "Wolof", text: "Nanga def ?", fr: "Comment vas-tu ?", weight: 3 },
  { lang: "Wolof", text: "Jamm nga fanaan ?", fr: "As-tu passé la nuit en paix ?", weight: 2 },
  { lang: "Wolof", text: "Maangi fi rekk", fr: "Je suis là, tout va bien", weight: 2 },
  { lang: "Wolof", text: "Jërëjëf", fr: "Merci", weight: 1 },
  { lang: "Pulaar (Peul · Toucouleur)", text: "No mbaɗɗa ?", fr: "Comment ça va ?", weight: 2 },
  { lang: "Pulaar (Peul · Toucouleur)", text: "Jam tan", fr: "En paix seulement", weight: 2 },
  { lang: "Pulaar (Peul · Toucouleur)", text: "A jaaraama", fr: "Merci", weight: 1 },
  { lang: "Joola", text: "Kasumay", fr: "Bonjour", weight: 1 },
  { lang: "Mandingue", text: "I ni sooma", fr: "Bonjour (matin)", weight: 1 },
];

/** Tirage pondéré : Sénégal (wolof) le plus fréquent. */
export function pickGreeting(exclude?: Greeting): Greeting {
  const pool = GREETINGS.filter((g) => g !== exclude);
  const total = pool.reduce((s, g) => s + g.weight, 0);
  let r = Math.random() * total;
  for (const g of pool) {
    r -= g.weight;
    if (r <= 0) return g;
  }
  return pool[0];
}
