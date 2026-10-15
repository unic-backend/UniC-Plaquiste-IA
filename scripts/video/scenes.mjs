// Scènes « HTML » (titre, texte, photo, galerie, chiffres, citation, fin) + pastilles de chapitre des scènes « page ».
// Rendu image par image dans Chrome : chaque image dépend uniquement du temps (déterministe). Entrée : plan.json écrit par make.py.
import { chromium } from "playwright";
import fs from "fs";
const PLAN = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const { w, h } = PLAN.view;
const FPS = +(process.env.VIDEO_FPS || PLAN.fps || 30);
if (![24, 30, 60].includes(FPS)) throw new Error('VIDEO_FPS doit être 24, 30 ou 60');
const b = await chromium.launch({ args: ["--font-render-hinting=none", "--disable-lcd-text"] });
const p = await (await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 3 })).newPage();
if (process.env.VIDEO_PRELOAD) await (await import(process.env.VIDEO_PRELOAD)).default(p);
await p.goto("file://" + new URL("./scenes.html", import.meta.url).pathname);
let n = 0;
for (const seg of PLAN.segments) {
  fs.mkdirSync(seg.out, { recursive: true });
  if (seg.kind === "html") {
    await p.evaluate(sc => window.setup(sc), seg.scene); await p.evaluate(() => window.ready());
    for (let f = 0; f < seg.frames; f++) {
      await p.evaluate(a => window.draw(a[0], a[1]), [f / FPS, seg.frames / FPS]);
      fs.writeFileSync(`${seg.out}/${String(f).padStart(5, "0")}.jpg`, await p.screenshot({ type: "jpeg", quality: 95 })); n++;
    }
  } else {   // pastilles : PNG transparents, seulement quand une pastille est visible
    await p.evaluate(() => window.pillMode()); const act = [];
    for (let f = 0; f < seg.frames; f++) {
      const t = f / FPS, on = seg.labels.find(l => t >= l.a - .05 && t <= l.b + .5) || null;
      if (!on) continue;
      await p.evaluate(a => window.pill(a[0], a[1]), [on, t]);
      fs.writeFileSync(`${seg.out}/${String(f).padStart(5, "0")}.png`, await p.screenshot({ omitBackground: true, type: "png" })); act.push(f); n++;
    }
    fs.writeFileSync(`${seg.out}/list.json`, JSON.stringify(act));
    await p.evaluate(() => window.pill(null, 0)); await p.evaluate(() => { document.querySelector("#root").style.display = ""; document.documentElement.style.background = document.body.style.background = ""; });
  }
}
console.log("scènes rendues :", n, "images"); await b.close();
