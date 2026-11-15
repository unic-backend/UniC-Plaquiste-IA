// Croquis Sketchy hors de l'appli : rapports, documents, vidéos (Claude Code). Même moteur que le chat UniC IA.
// usage : node scripts/croquis.mjs scene.txt dossier/ [--largeur 1080] [--echelle 2]   (--echelle 4 : images nettes pour une vidéo 1080)
// sortie : croquis.png (dessin entier), etape-1.png… (une image par étape, entourée en rouge), croquis.svg,
//          croquis.html + sketchy.js (page interactive, sans Internet), etapes.json (titre et texte de chaque étape).
// Scène : la syntaxe de frontend/public/vendor/sketchy (voir docs/skills/unic-croquis/SKILL.md). Jamais de coordonnées.
import { createRequire } from "module";
import fs from "fs";
import path from "path";
const { chromium } = createRequire(import.meta.url)("playwright");   // require suit NODE_PATH (Playwright installé hors du dépôt)

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i < 0 ? def : args.splice(i, 2)[1]; };
const width = Number(opt("--largeur", "1080"));
const scale = Number(opt("--echelle", "2"));
const [SCENE, OUT] = args;
if (!SCENE || !OUT) { console.error("usage : node scripts/croquis.mjs scene.txt dossier/ [--largeur 1080] [--echelle 2]"); process.exit(2); }
const scene = fs.readFileSync(SCENE, "utf8");
const BUNDLE = new URL("../frontend/public/vendor/sketchy/sketchy.js", import.meta.url).pathname;
fs.mkdirSync(OUT, { recursive: true });

// Page autonome : le moteur est copié à côté (il lit son adresse pour trouver ses fichiers, donc pas en ligne), la scène passe en JSON.
const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Croquis</title><style>body{margin:0;padding:16px;background:#fff;font-family:system-ui}#s{max-width:${width}px;margin:auto}body.shot #s button{visibility:hidden!important}</style></head>
<body><div id="s"></div><script src="sketchy.js"></script>
<script>Sketchy.draw("#s", ${JSON.stringify(scene).replace(/</g, "\\u003c")});</script></body></html>`;
fs.writeFileSync(path.join(OUT, "croquis.html"), html);
fs.copyFileSync(BUNDLE, path.join(OUT, "sketchy.js"));

const b = await chromium.launch();
try {
  const p = await (await b.newContext({ viewport: { width: width + 32, height: 900 }, deviceScaleFactor: scale })).newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto("file://" + path.resolve(OUT, "croquis.html"));
  const svg = p.locator("#s svg").first();
  try { await svg.waitFor({ timeout: 15000 }); } catch { throw new Error(`Croquis impossible : ${(await p.textContent("#s")) || errors.join(" ; ")}`); }
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(300);
  // image propre : boutons de navigation masqués le temps de la capture
  const shot = async (file) => { await p.evaluate(() => document.body.classList.add("shot")); await svg.screenshot({ path: path.join(OUT, file) });
    await p.evaluate(() => document.body.classList.remove("shot")); };
  await shot("croquis.png");
  fs.writeFileSync(path.join(OUT, "croquis.svg"), await svg.evaluate((e) => e.outerHTML));
  // Étapes : celles écrites dans la scène (« step Titre: texte | ids »), rendues une par une avec le bouton « étape suivante ».
  const steps = scene.split("\n").map((l) => l.match(/^\s*step\s+([^:|]+):\s*([^|]*)/)).filter(Boolean)
    .map((m) => ({ titre: m[1].trim(), texte: m[2].trim() }));
  for (let i = 0; i < steps.length; i++) {
    await p.locator('#s button[aria-label="Next step"]').click();
    await p.waitForTimeout(700);   // le trait rouge et le fondu sont animés
    steps[i].image = `etape-${i + 1}.png`;
    await shot(steps[i].image);
  }
  fs.writeFileSync(path.join(OUT, "etapes.json"), JSON.stringify(steps, null, 1));
  console.log(`croquis : ${OUT}/croquis.png, ${steps.length} étape(s), croquis.svg, croquis.html`);
} finally {
  await b.close();
}
