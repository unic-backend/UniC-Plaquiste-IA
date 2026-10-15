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
await p.goto("file://" + new URL("./scenes.html", import.meta.url).pathname);
let n = 0, blk = 0, mode = "";
const setMode = async m => {   // "html" ou "pill" : on ne bascule que si nécessaire
  if (mode === m) return;
  if (m === "pill") await p.evaluate(() => window.pillMode());
  else await p.evaluate(() => { window.pill(null, 0); document.querySelector("#root").style.display = ""; document.documentElement.style.background = document.body.style.background = ""; });
  mode = m;
};
const ONLY = process.env.ONLY || "";   // "html" : scènes seules (avant la fin des captures de pages) ; "pill" : pastilles seules
for (const seg of PLAN.segments) {
  if (ONLY && (ONLY === "html") !== (seg.kind === "html")) continue;
  fs.mkdirSync(seg.out, { recursive: true });
  const act = []; let ready = false;
  for (let start = 0; start < seg.frames; start += BLOCK) {
    if (blk++ % WORKERS !== WORKER) continue;   // paquet traité par un autre Chrome
    const end = Math.min(seg.frames, start + BLOCK);
    if (seg.kind === "html") {
      await setMode("html");
      if (!ready) { await p.evaluate(sc => window.setup(sc), seg.scene); await p.evaluate(() => window.ready()); ready = true; }
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
  if (seg.kind !== "html") fs.writeFileSync(`${seg.out}/list.${WORKER}.json`, JSON.stringify(act));
}
console.log(`Chrome ${WORKER + 1}/${WORKERS} : ${n} images`); await b.close();
