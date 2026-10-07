/** Parole au fil de l'eau : dès qu'une phrase complète arrive, UniC la dit, pendant que la suite s'écrit encore.
 *  Pur (sans voix ni réseau) : la lecture réelle est injectée, ce qui permet de le tester. */
const MIN_CHARS = 20;   // évite de dire « M. » ou « Oui. » seul : les phrases courtes se regroupent

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
    await Promise.all(this.pending);
  }

  cancel(): void { this.dead = true; this.buf = ""; this.stopAll(); }
}
