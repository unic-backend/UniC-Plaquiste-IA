/** Parole au fil de l'eau : dès qu'une phrase complète arrive, UniC la dit, pendant que la suite s'écrit encore.
 *  Pur (sans voix ni réseau) : la lecture réelle est injectée, ce qui permet de le tester. */
const MIN_CHARS = 20;   // évite de dire « M. » ou « Oui. » seul : les phrases courtes se regroupent

const SPACED_THOUSANDS = /(?<![\d,.])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)/g;
const UNITS: [RegExp, string][] = [
  [/(?<=\d)\s*(?:m²|m2)(?![\p{L}\d_])/gu, " mètres carrés"],
  [/(?<=\d)\s*ml(?![\p{L}\d_])/gu, " mètres linéaires"],
  [/(?<=\d)\s*mm(?![\p{L}\d_])/gu, " millimètres"],
  [/(?<=\d)\s*cm(?![\p{L}\d_])/gu, " centimètres"],
  [/(?<=\d)\s*m(?![\p{L}\d_²])/gu, " mètres"],
  [/(?<=\d)\s*kg(?![\p{L}\d_])/gu, " kilos"],
  [/(?<=\d)\s*[lL](?![\p{L}\d_'’])/gu, " litres"],
  [/(?<=\d)\s*h\s*(?=\d)/g, " heures "],
  [/(?<=\d)\s*h(?![\p{L}\d_])/gu, " heures"],
];

/** Montants et mesures dits comme un humain (même règle que voice.speech_numbers côté serveur) :
 *  « 1 250 000 FCFA » → « 1250000 francs CFA » (la voix dit « un million… », pas « un, deux cent cinquante, zéro zéro zéro »),
 *  « 12 x 2,5 m » → « 12 par 2,5 mètres », « BA13 » → « B A 13 ». */
export function speechNumbers(t: string): string {
  t = t.replace(SPACED_THOUSANDS, (m) => m.replace(/[ \u00a0\u202f]/g, ""))
    .replace(/(?<=\d)\s*[x×*]\s*(?=\d)/g, " par ")
    .replace(/\b(?:F\s?CFA|FCFA|XOF)\b/g, "francs CFA")
    .replace(/\bBA\s?(\d{2})\b/g, "B A $1")
    .replace(/\bN[°o]\s?(?=\d)/g, "numéro ");
  for (const [re, words] of UNITS) t = t.replace(re, words);
  return t.replace(/\s*[→—–]\s*/g, ", ");
}

/** Texte lisible à voix haute : sans Markdown, tableaux, liens ni sources (le serveur nettoie aussi, par sécurité). */
export function speakable(text: string): string {
  const t = text.split("\n\n**Sources**")[0]
    .replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s*\|.*\|\s*$/gm, " ").replace(/^\s{0,3}#{1,6}\s*/gm, "").replace(/^\s*[-*•]\s+/gm, "")
    .replace(/[*_`>~]+/g, "");
  return speechNumbers(t).replace(/\s*\n+\s*/g, ". ").replace(/\s{2,}/g, " ").replace(/\.{2,}/g, ".").trim();
}

/** Sort les phrases complètes du tampon ; ce qui reste attend la suite. Un point suivi d'un chiffre (3.5) ne coupe pas. */
export function takeSentences(buf: string): { ready: string[]; rest: string } {
  const ready: string[] = [];
  let rest = buf;
  for (;;) {
    const m = /^([\s\S]{20,}?[.!?…])(?:["»)]*)(\s+)/.exec(rest) || /^([\s\S]{1,}?)\n+/.exec(rest);
    if (!m || m[1].trim().length < MIN_CHARS && !/\n/.test(m[0])) break;
    ready.push(m[1].trim());
    rest = rest.slice(m[0].length);
  }
  return { ready, rest };
}

export class SpeechPipeline {
  private buf = "";
  private pending: Promise<void>[] = [];
  private dead = false;
  private release: () => void = () => {};
  /** Se résout à l'annulation : une voix qui ne signale jamais sa fin (audio ElevenLabs mis en pause) ne bloque plus l'écoute. */
  private cancelled = new Promise<void>((r) => { this.release = r; });
  /** sayPart lance la phrase TOUT DE SUITE : le moteur de voix met les phrases en file et les enchaîne sans temps mort. */
  constructor(private sayPart: (t: string) => Promise<void>, private stopAll: () => void) {}

  push(delta: string): void {
    if (this.dead || !delta) return;
    this.buf += delta;
    const { ready, rest } = takeSentences(this.buf);
    this.buf = rest;
    for (const s of ready) this.enqueue(s);
  }

  private enqueue(t: string): void {
    if (this.dead) return;
    this.pending.push(this.sayPart(t).catch(() => { /* une phrase qui échoue ne bloque pas les suivantes */ }));
  }

  /** La réponse est complète : on dit ce qui reste, puis on rend la main quand tout est dit. */
  async finish(): Promise<void> {
    if (!this.dead && this.buf.trim()) this.enqueue(this.buf.trim());
    this.buf = "";
    await Promise.race([Promise.all(this.pending), this.cancelled]);
  }

  /** Coupe tout (patron qui reprend la parole, écran fermé) : plus rien n'est dit et finish() rend la main tout de suite. */
  cancel(): void { this.dead = true; this.buf = ""; this.stopAll(); this.release(); }
}
