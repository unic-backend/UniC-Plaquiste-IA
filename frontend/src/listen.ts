import { isNative } from "./api";
import { ear } from "./phone";
import { ding } from "./speech";

/** Une écoute : rend ce que le patron a dit ("" si silence). Écoute native Android (signaux exacts) ou reconnaissance du navigateur. */
const ERR_TEXT: Record<number, string> = {
  1: "Pas de réseau pour la reconnaissance vocale.", 2: "Pas de réseau pour la reconnaissance vocale.", 3: "Le micro est occupé par une autre appli.",
  5: "La reconnaissance vocale s'est arrêtée.", 8: "Le moteur de dictée est occupé.", 9: "Micro refusé : autorise-le dans Réglages › Applis › UniC AI › Autorisations.",
  10: "Le moteur de dictée est surchargé.", 11: "Le moteur de dictée du téléphone est indisponible.", 12: "Langue française non disponible pour la dictée.", 13: "Langue française non disponible pour la dictée.",
};
export async function listenOnce(onHear?: (text: string) => void, onReady?: () => void, lang = "fr-FR", signal?: AbortSignal): Promise<string> {
  if (isNative) {
    return new Promise<string>((resolve, reject) => {
      let heard = "", done = false, retries = 0, timer: ReturnType<typeof setTimeout> | undefined, openTimer: ReturnType<typeof setTimeout> | undefined;
      const handles: { remove(): Promise<void> }[] = [];
      const cleanup = () => { clearTimeout(timer); clearTimeout(openTimer); handles.forEach((h) => h.remove().catch(() => {})); ear.stop(); };
      const finish = () => { if (done) return; done = true; cleanup(); resolve(heard.trim()); };
      const fail = (m: string) => { if (done) return; done = true; cleanup(); reject(new Error(m)); };
      const arm = (ms: number) => { clearTimeout(timer); timer = setTimeout(finish, ms); };
      signal?.addEventListener("abort", () => { if (done) return; done = true; cleanup(); resolve(""); });   // arrêt demandé (touche, fermeture) : on rend la main tout de suite
      const begin = () => ear.start(lang).catch((e) => fail(e?.message || "Le micro n'a pas pu s'ouvrir."));
      (async () => {
        handles.push(await ear.on("ready", () => { clearTimeout(openTimer); onReady?.(); ding(660, 0.05); arm(15000); }));   // le micro est réellement ouvert : écran et signal sonore ensemble
        handles.push(await ear.on("partial", (d) => { if (d.text) { heard = d.text; onHear?.(heard); } }));
        handles.push(await ear.on("final", (d) => { if (d.text) heard = d.text; finish(); }));
        handles.push(await ear.on("error", (d) => {
          const c = d.code ?? 0;
          if (c === 6 || c === 7) { finish(); return; }                                          // silence ou rien compris : on rend ce qu'on a
          if ((c === 3 || c === 5 || c === 8) && retries++ < 2) { setTimeout(() => { if (!done) begin(); }, 450); return; }   // micro pas encore libre : on réessaie
          fail(ERR_TEXT[c] || `La dictée a échoué (code ${c}).`);
        }));
        openTimer = setTimeout(() => fail("Le micro ne s'ouvre pas. Ferme les autres applis qui l'utilisent, puis touche la bille."), 6000);   // le micro ne s'est jamais ouvert : on le dit, on ne reste pas bloqué
        await begin();
      })().catch((e) => fail(e?.message || "Micro indisponible"));
    });
  }
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) throw new Error("Dictée indisponible sur ce navigateur.");
  return new Promise<string>((resolve) => {
    const r = new SR();
    signal?.addEventListener("abort", () => { try { r.abort(); } catch { /* déjà arrêté */ } resolve(""); });
    r.lang = lang; r.interimResults = false; r.maxAlternatives = 1;
    let text = "";
    r.onresult = (e: any) => { text = Array.from(e.results).map((x: any) => x[0].transcript).join(" "); onHear?.(text); };
    r.onend = () => resolve(text.trim());
    r.onerror = () => resolve(text.trim());
    r.onstart = () => { onReady?.(); };
    r.start();
    setTimeout(() => { try { r.stop(); } catch { /* déjà arrêté */ } }, 15000);
  });
}
