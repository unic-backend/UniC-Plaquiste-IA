// Scènes « HTML » (titre, texte, photo, galerie, chiffres, citation, fin) + pastilles de chapitre des scènes « page ».
// Rendu image par image dans Chrome : chaque image dépend uniquement du temps (déterministe). Entrée : plan.json écrit par make.py.
import { chromium } from "playwright";
import fs from "fs";
const PLAN = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const { w, h } = PLAN.view;
const FPS = +(process.env.VIDEO_FPS || PLAN.fps || 60);
const WORKER = +(process.env.WORKER || 0), WORKERS = +(process.env.WORKERS || 1), BLOCK = 120;   // images rendues par paquets de 120, répartis entre les Chrome
if (![24, 30, 60].includes(FPS)) throw new Error('VIDEO_FPS doit être 24, 30 ou 60');
const b = await chromium.launch({ args: ["--font-render-hinting=none", "--disable-lcd-text"] });
const p = await (await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 3 })).newPage();
if (process.env.VIDEO_PRELOAD) await (await import(process.env.VIDEO_PRELOAD)).default(p);
const TRIES = 4, pause = ms => new Promise(r => setTimeout(r, ms));
// Polices vérifiées avant la première image : sans elles, ce tronçon sortirait dans une autre police que les autres (vidéo disparate).
for (let i = 1; ; i++) {
  if (i === 1) await p.goto("file://" + new URL("./scenes.html", import.meta.url).pathname); else await p.reload();
  const miss = await p.evaluate(() => window.fontsOk());
  if (!miss.length) break;
  if (i >= TRIES) throw new Error(`polices introuvables après ${i} essais (réseau) : ${miss.join(", ")}`);
  await pause(2000 * i);
}
await p.evaluate(t => { document.documentElement.dataset.theme = t; }, PLAN.theme || "unic");
// Images d'une scène : réessayées, puis erreur claire (une photo manquante donnait une scène vide, sans le dire).
const settle = async () => {
  for (let i = 1; ; i++) {
    const bad = await p.evaluate(() => window.ready());
    if (!bad.length) return;
    if (i >= TRIES) throw new Error(`image injoignable après ${i} essais : ${String(bad[0]).slice(0, 120)}`);
    await pause(2000 * i);
    await p.evaluate(() => window.reloadImages());
  }
};
let n = 0, blk = 0, mode = "";
const setMode = async m => {   // "html", "pill" ou "ovl" (texte incrusté sur un clip) : on ne bascule que si nécessaire
  if (mode === m) return;
  if (m === "pill") await p.evaluate(() => { window.overlayMode(false); window.pillMode(); });
  else await p.evaluate(o => { window.pill(null, 0); window.overlayMode(o); document.querySelector("#root").style.display = ""; document.documentElement.style.background = document.body.style.background = ""; }, m === "ovl");
  mode = m;
};
const ONLY = process.env.ONLY || "";   // "html" : scènes seules (avant la fin des captures de pages) ; "pill" : pastilles seules
for (const seg of PLAN.segments) {
  if (seg.kind === "clip" && !seg.panels && !seg.caps && seg.layout !== "split") continue;   // film : déjà mis en images par make.py
  const htmlLike = seg.kind === "html" || seg.kind === "clip";   // l'incrustation d'un clip ne dépend pas des pages
  if (ONLY && (ONLY === "html") !== htmlLike) continue;
  fs.mkdirSync(seg.out, { recursive: true });
  const act = []; let ready = false;
  for (let start = 0; start < seg.frames; start += BLOCK) {
    if (blk++ % WORKERS !== WORKER) continue;   // paquet traité par un autre Chrome
    const end = Math.min(seg.frames, start + BLOCK);
    if (seg.kind === "clip") {   // texte incrusté : PNG transparents, posés sur les images du film par compose.py
      await setMode("ovl"); fs.mkdirSync(seg.ovl, { recursive: true });
      // animations les unes après les autres (panels : [début, avance, animation]) ; sous-titres sur toute la scène
      const P = seg.panels || [], dur = seg.frames / FPS; let cur = -2;
      for (let f = start; f < end; f++) {
        const t = f / FPS; let k = -1; for (let j = 0; j < P.length; j++) if (P[j][0] <= t + 1e-6) k = j;
        if (k !== cur || !ready) { await p.evaluate(sc => window.setup(sc), { ...(k >= 0 ? P[k][2] : { type: "captions" }), caps: seg.caps || [], layout: seg.layout || "full" }); cur = k; ready = true; }
        const a = k >= 0 ? P[k][0] : 0, adv = k >= 0 ? P[k][1] : 0, b = k >= 0 && k + 1 < P.length ? P[k + 1][0] : dur;
        await p.evaluate(x => window.draw(x[0], x[1], x[2], x[3]), [t - a + adv, b - a + adv, t, k + 1 < P.length]);
        fs.writeFileSync(`${seg.ovl}/${String(f).padStart(5, "0")}.png`, await p.screenshot({ omitBackground: true, type: "png" })); n++;
      }
    } else if (seg.kind === "html") {
      await setMode("html");
      if (!ready) { await p.evaluate(sc => window.setup(sc), seg.scene); await settle(); ready = true; }
      for (let f = start; f < end; f++) {
        await p.evaluate(a => window.draw(a[0], a[1]), [f / FPS, seg.frames / FPS]);
        fs.writeFileSync(`${seg.out}/${String(f).padStart(5, "0")}.jpg`, await p.screenshot({ type: "jpeg", quality: 95 })); n++;
      }
    } else {   // pastilles : PNG transparents, seulement quand une pastille est visible
      await setMode("pill");
      for (let f = start; f < end; f++) {
        const t = f / FPS, on = seg.labels.find(l => t >= l.a - .05 && t <= l.b + .5) || null;
        if (!on) continue;
        await p.evaluate(a => window.pill(a[0], a[1]), [on, t]);
        fs.writeFileSync(`${seg.out}/${String(f).padStart(5, "0")}.png`, await p.screenshot({ omitBackground: true, type: "png" })); act.push(f); n++;
      }
    }
  }
  if (seg.kind === "page") fs.writeFileSync(`${seg.out}/list.${WORKER}.json`, JSON.stringify(act));
}
console.log(`Chrome ${WORKER + 1}/${WORKERS} : ${n} images`); await b.close();
