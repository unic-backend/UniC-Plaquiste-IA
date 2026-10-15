// Capture déterministe image par image d'une page (Playwright). Entrée : spec.json, dossier de sortie.
// Horloge virtuelle + animations CSS pilotées à la main + défilement au pixel physique : le résultat ne dépend pas de la vitesse de la machine.
import { chromium } from "playwright";
import fs from "fs";
const [SPEC, DIR, VIEW] = process.argv.slice(2);
const S = JSON.parse(fs.readFileSync(SPEC, "utf8"));
const V = JSON.parse(VIEW || '{"w":360,"h":640,"scale":3,"mobile":true}');
const CAP = +(process.env.VIDEO_FPS || 30), SCALE = V.scale, W = V.w, H = V.h, DT = 1000 / CAP, dt = 1 / CAP, LIMIT = +(process.env.LIMIT || 1e9);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v)), lerp = (a, b, x) => a + (b - a) * x;
const sm = x => { x = clamp(x, 0, 1); return x * x * x * (x * (x * 6 - 15) + 10); };
fs.mkdirSync(DIR, { recursive: true });

const b = await chromium.launch({ args: ["--font-render-hinting=none", "--disable-lcd-text"] });
const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: SCALE, isMobile: V.mobile, hasTouch: V.mobile });
const p = await ctx.newPage();
await p.addInitScript(() => { const q = []; let id = 0;
  window.requestAnimationFrame = cb => { q.push([++id, cb]); return id; };
  window.cancelAnimationFrame = i => { const k = q.findIndex(e => e[0] === i); if (k >= 0) q.splice(k, 1); };
  window.__tick = t => { const run = q.splice(0); run.forEach(([, cb]) => { try { cb(t); } catch (e) { console.error(e); } }); }; });
if (process.env.VIDEO_PRELOAD) await (await import(process.env.VIDEO_PRELOAD)).default(p);   // tests : routes locales (polices, images)
await p.clock.install({ time: 0 });
await p.clock.pauseAt(1000);
await p.goto(S.url, { waitUntil: "load" });
await p.evaluate(async () => {
  document.documentElement.style.scrollBehavior = "auto";
  const st = document.createElement("style");
  st.textContent = ".card,.card img,.stile,.collage img,#words,#tag,#track,#sprog,#prog{will-change:transform}";   // couches composées : pas de scintillement du texte
  document.head.appendChild(st);
  document.querySelectorAll("img").forEach(i => i.loading = "eager");
  await Promise.all([...document.images].map(i => i.complete && i.naturalWidth ? 1 : new Promise(r => { i.onload = i.onerror = r; })));
  await document.fonts.ready;
});
const max = await p.evaluate(() => document.documentElement.scrollHeight - innerHeight);
const geo = await Promise.all(S.chapters.map(c => p.evaluate(sel => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top + scrollY, h: r.height }; }, c.selector)));
geo.forEach((g, i) => { if (!g) console.log("sélecteur introuvable :", S.chapters[i].selector); });

// ---- plan de défilement : arrivée douce sur chaque chapitre, puis lecture ; un grand bloc est parcouru en entier
const TRAVEL = 1.6, K = [[0, 0], [S.hero_seconds, 0]]; let t = S.hero_seconds; const labels = [], zoomAt = [];
S.chapters.forEach((c, i) => { const g = geo[i]; if (!g) return;
  const y0 = clamp(g.top - 30, 0, max), y1 = clamp(g.top + g.h - H + 30, y0, max), tall = g.h > H * 1.5;
  const arrive = t + TRAVEL, leave = t + c.seconds;
  K.push([arrive, y0], [Math.max(arrive + .2, leave), tall ? y1 : y0 + (y1 - y0) * .25]);
  labels.push([t + .3, leave - .1, String(labels.length + 1).padStart(2, "0"), c.label]); if (!tall) zoomAt.push([arrive + .2, leave - .3]); t = leave; });
K.push([t + 1.8, max], [t + 40, max]);
const endAt = t + 1.8;
const pchip = P => { const n = P.length, h = [], d = [], m = new Array(n).fill(0);
  for (let i = 0; i < n - 1; i++) { h[i] = P[i + 1][0] - P[i][0]; d[i] = (P[i + 1][1] - P[i][1]) / h[i]; }
  for (let i = 1; i < n - 1; i++) { if (d[i - 1] * d[i] <= 0) m[i] = 0; else { const w1 = 2 * h[i] + h[i - 1], w2 = h[i] + 2 * h[i - 1]; m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]); } }
  return x => { if (x <= P[0][0]) return P[0][1]; let i = 0; while (i < n - 2 && x > P[i + 1][0]) i++; if (x >= P[n - 1][0]) return P[n - 1][1];
    const s = (x - P[i][0]) / h[i], s2 = s * s, s3 = s2 * s;
    return (2 * s3 - 3 * s2 + 1) * P[i][1] + (s3 - 2 * s2 + s) * h[i] * m[i] + (-2 * s3 + 3 * s2) * P[i + 1][1] + (s3 - s2) * h[i] * m[i + 1]; }; };
const scrollAt = pchip(K);
const zoomTarget = x => { for (const [a, c] of zoomAt) if (x >= a - .8 && x <= c + .8) return 1 + .06 * sm(Math.min((x - (a - .8)) / .8, ((c + .8) - x) / .8)); return 1; };
const spring = (s, target, w) => { s.v += (-2 * w * s.v - w * w * (s.p - target)) * dt; s.p += s.v * dt; };
const SS = { p: 0, v: 0 }, SZ = { p: 1, v: 0 };
const cdp = await ctx.newCDPSession(p);
const frames = Math.min(LIMIT, Math.round(endAt * CAP)), meta = []; let vnow = 1000;
for (let f = 0; f < frames; f++) {
  const x = f / CAP;
  await p.clock.runFor(DT); vnow += DT;
  spring(SS, scrollAt(x), 14); spring(SZ, zoomTarget(x), 9);
  const want = clamp(SS.p, 0, max), yq = Math.round(want * SCALE) / SCALE;
  const sy = await p.evaluate(({ vn, y }) => {
    document.getAnimations().forEach(a => { if (a.__t0 === undefined) a.__t0 = vn; a.pause(); a.currentTime = vn - a.__t0; });
    window.scrollTo({ top: y, behavior: "instant" });
    window.dispatchEvent(new Event("scroll"));
    window.__tick(vn); return window.scrollY; }, { vn: vnow, y: yq });
  const r = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 95, optimizeForSpeed: true, clip: { x: 0, y: sy, width: W, height: H, scale: SCALE } });
  fs.writeFileSync(`${DIR}/${String(f).padStart(5, "0")}.jpg`, Buffer.from(r.data, "base64"));
  meta.push([+(want - sy).toFixed(4), +SZ.p.toFixed(5)]);
  if (f % 300 === 0) console.log(`${(x).toFixed(1)}s ${f}/${frames}`);
}
fs.writeFileSync(`${DIR}/meta.json`, JSON.stringify({ W, H, SCALE, CAP, frames, meta, labels: labels.map(l => ({ a: l[0], b: l[1], n: l[2], label: l[3] })), endAt }));
await b.close(); console.log("capture terminée", frames, "images");
