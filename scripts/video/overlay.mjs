// Incrustations (ouverture, titres de chapitre, carte de fin) : rendues image par image, fond transparent.
import { chromium } from "playwright";
import fs from "fs";
const [SPEC, FRAMES, DIR] = process.argv.slice(2);
const S = JSON.parse(fs.readFileSync(SPEC, "utf8")), M = JSON.parse(fs.readFileSync(`${FRAMES}/meta.json`, "utf8"));
const P = 2.6, total = P + M.endAt + 4.2, N = Math.round(total * 60);
fs.mkdirSync(DIR, { recursive: true });
const b = await chromium.launch({ args: ["--font-render-hinting=none", "--disable-lcd-text"] });
const p = await (await b.newContext({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 3 })).newPage();
if (process.env.VIDEO_PRELOAD) await (await import(process.env.VIDEO_PRELOAD)).default(p);
await p.goto("file://" + new URL("./overlay.html", import.meta.url).pathname); await p.evaluate(() => document.fonts.ready);
await p.evaluate(c => window.setup(c), { title: S.title, subtitle: S.subtitle, end: S.end, P, total, labels: M.labels, endAt: M.endAt });
const act = [];
for (let n = 0; n < N; n++) { const T = n / 60, t = T - P;
  if (!(T < P || M.labels.some(l => t >= l[0] - .05 && t <= l[1] + .5) || t >= M.endAt)) continue;
  await p.evaluate(T => window.draw(T), T);
  fs.writeFileSync(`${DIR}/${String(n).padStart(5, "0")}.png`, await p.screenshot({ omitBackground: true, type: "png" })); act.push(n); }
fs.writeFileSync(`${DIR}/list.json`, JSON.stringify({ act, total, P })); console.log("incrustations", act.length); await b.close();
