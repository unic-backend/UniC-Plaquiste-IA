// Scènes 3D du moteur : vue éclatée en couches (layers3d) et salon 3D dont le plafond s'allume (room3d).
// Three.js (MIT, copie locale dans three/) ; rendu logiciel possible (pas de carte graphique). Chaque image ne dépend que du temps t :
// rien n'est animé par une horloge, une image se recalcule à l'identique (rendu par paquets, dans le désordre).
import * as THREE from "./three/three.module.js";

const cl = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x)), seg = (t, a, b) => cl((t - a) / (b - a));
const io = x => (x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2), out = x => 1 - Math.pow(1 - x, 3);
const back = x => { const c = 1.7; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const theme = n => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#ffffff");
const div = (cls, txt, parent, css) => { const e = document.createElement("div"); e.className = cls; e.textContent = txt; e.style.cssText = css; parent.appendChild(e); return e; };   // textContent : aucun texte du scénario n'est lu comme du HTML

function stage(root) {   // toile plein cadre, fond transparent : l'ambiance de couleurs (thème) reste derrière
  const cv = document.createElement("canvas"), W = innerWidth, H = innerHeight;
  cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%"; root.appendChild(cv);
  const r = new THREE.WebGLRenderer({ canvas: cv, antialias: true, alpha: true, preserveDrawingBuffer: true });
  r.setPixelRatio(devicePixelRatio); r.setSize(W, H, false); r.setClearColor(0x000000, 0); r.outputColorSpace = THREE.SRGBColorSpace;
  return { r, W, H, dispose: () => { r.dispose(); r.forceContextLoss(); } };
}

// Vue éclatée : 2 à 6 couches (de haut en bas) se séparent ; chaque légende est reliée à sa couche, en colonne, sans croisement.
function layers(sc, root, u) {
  const { r, W, H, dispose } = stage(root), scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(30, W / H, .1, 200), n = sc.layers.length;
  const fg = theme("--fg"), gold = theme("--gold"), royal = theme("--royal"), wide = W > H;
  scene.add(new THREE.HemisphereLight(0xffffff, royal, 2.2));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(4, 7, 5); scene.add(key);
  const S = 2.4, TH = [.16, .3, .12, .24, .2, .1], GAP = wide ? .78 : 1.05, slabs = [];   // en portrait, la hauteur de l'image sert à écarter les couches
  let y = 0;
  sc.layers.forEach((_, i) => {
    const th = TH[i % TH.length], c = i === 0 ? gold.clone() : fg.clone().lerp(royal, .12 + .5 * i / Math.max(1, n - 1));   // la couche du dessus en couleur d'accent
    const geo = new THREE.BoxGeometry(S, th, S), g = new THREE.Group();
    g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: c, roughness: .55, metalness: .05 })));
    g.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: fg, transparent: true, opacity: .55 })));
    slabs.push({ g, th, stack: y - th / 2, open: ((n - 1) / 2 - i) * GAP }); y -= th + .015; scene.add(g);
  });
  const mid = y / 2; slabs.forEach(s => { s.stack -= mid; });
  // cadrage : l'objet éclaté tient dans le cadre, décalé à gauche (portrait) pour laisser la colonne des légendes
  const half = (n - 1) * GAP / 2 + 1.1,   // + le dessus des plaques vu de haut
        vfov = THREE.MathUtils.degToRad(cam.fov), hfov = 2 * Math.atan(Math.tan(vfov / 2) * cam.aspect);
  const R = Math.max(half / Math.tan(vfov / 2) * (sc.heading ? 1.3 : 1.1), S * 1.41 / (2 * Math.tan(hfov / 2) * (wide ? .42 : .56)));   // l'objet occupe ~56 % de la largeur en portrait
  cam.setViewOffset(W, H, W * (wide ? .13 : .17), sc.heading ? -H * .05 : 0, W, H);   // décalé à gauche (légendes) et vers le bas (titre)
  const ov = div("l3", "", root, "position:absolute;inset:0;pointer-events:none"), svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.style.cssText = "position:absolute;inset:0;overflow:visible"; ov.appendChild(svg);
  const colX = W * (wide ? .64 : .66), colW = W - colX - 14 * u;
  const tags = sc.layers.map(txt => {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline"), dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    line.setAttribute("fill", "none"); line.setAttribute("stroke", "var(--fg)"); line.setAttribute("stroke-opacity", ".7"); line.setAttribute("stroke-width", 1.4 * u);
    dot.setAttribute("r", 3.2 * u); dot.setAttribute("fill", "var(--gold)"); svg.append(line, dot);
    const lab = div("", txt, ov, `position:absolute;left:${colX}px;width:${colW}px;font:700 ${15 * u}px/1.08 "Barlow Condensed",sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--fg);transform:translateY(-50%)`);
    return { line, dot, lab };
  });
  const head = sc.heading ? div("", sc.heading, ov, `position:absolute;left:${16 * u}px;right:${16 * u}px;top:${H * .07}px;text-align:center;font:400 ${30 * u}px/1.05 Anton,Impact,sans-serif;color:var(--fg);text-transform:uppercase`) : null;
  const p = new THREE.Vector3();
  return {
    draw(t, dur) {
      const pop = back(seg(t, .1, .8)), a = THREE.MathUtils.degToRad(32 + 26 * io(seg(t, 0, dur))), el = THREE.MathUtils.degToRad(24);
      cam.position.set(Math.sin(a) * Math.cos(el) * R, Math.sin(el) * R, Math.cos(a) * Math.cos(el) * R); cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
      const ex = i => io(seg(t, .9 + .1 * i, 2.3 + .1 * i));
      slabs.forEach((s, i) => { s.g.scale.setScalar(Math.max(1e-4, pop)); s.g.position.y = (s.stack + (s.open - s.stack) * ex(i)) * pop; });
      scene.updateMatrixWorld(); r.render(scene, cam);
      tags.forEach((o, i) => {   // ancre : coin avant droit de la couche, projeté à l'écran
        const s = slabs[i], k = out(seg(t, 2.0 + .15 * i, 2.5 + .15 * i));
        p.set(S / 2, s.g.position.y, S / 2).project(cam);
        const ax = (p.x + 1) / 2 * W, ay = (1 - p.y) / 2 * H, ly = ay;   // la projection tient déjà compte du décalage du cadre
        const x1 = colX - 8 * u, xm = ax + (x1 - ax) * .35;
        o.line.setAttribute("points", `${ax},${ay} ${xm},${ly} ${ax + (x1 - ax) * k},${ly}`); o.line.style.opacity = k;
        o.dot.setAttribute("cx", ax); o.dot.setAttribute("cy", ay); o.dot.style.opacity = k;
        o.lab.style.top = ly + "px"; o.lab.style.opacity = out(seg(t, 2.3 + .15 * i, 2.8 + .15 * i));
      });
      if (head) { const k = out(seg(t, .2, .8)); head.style.opacity = k; head.style.transform = `translateY(${(1 - k) * 20 * u}px)`; }
    },
    dispose,
  };
}

// Salon 3D façon dessin animé : la caméra entre, les caissons sortent du plafond, la LED puis les spots s'allument (couleur d'accent du thème).
function room(sc, root, u) {
  const { r, W, H, dispose } = stage(root), scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(W > H ? 42 : 50, W / H, .1, 100);
  const tones = new THREE.DataTexture(new Uint8Array([70, 150, 255]), 3, 1, THREE.RedFormat);   // 3 tons de lumière : rendu « dessin animé »
  tones.minFilter = tones.magFilter = THREE.NearestFilter; tones.needsUpdate = true;
  const ink = new THREE.MeshBasicMaterial({ color: 0x14141c, side: THREE.BackSide }), toon = c => new THREE.MeshToonMaterial({ color: c, gradientMap: tones });
  const room = new THREE.Group(); scene.add(room);
  const part = (geo, mat, x, y, z) => {   // objet + contour noir (copie retournée un peu plus grande)
    const g = new THREE.Group(), o = new THREE.Mesh(geo, ink), s = new THREE.Vector3(); geo.computeBoundingBox(); geo.boundingBox.getSize(s);
    o.scale.set((s.x + .05) / s.x, (s.y + .05) / s.y, (s.z + .05) / s.z); g.add(o, new THREE.Mesh(geo, mat)); g.position.set(x, y, z); room.add(g); return g;
  };
  const box = (w, h, d, c, x, y, z) => part(new THREE.BoxGeometry(w, h, d), toon(c), x, y, z);
  box(4.4, .2, 4.4, 0xd9a066, 0, -.1, 0); box(4.4, 2.8, .2, 0xf3e3c3, 0, 1.4, -2.1); box(.2, 2.8, 4.2, 0xf0dcb6, -2.1, 1.4, .1); box(4.4, .2, 4.4, 0xe9e1d3, 0, 2.9, 0);
  part(new THREE.CylinderGeometry(1.05, 1.05, .03, 48), toon(0xff7a59), .2, .015, -.2);
  box(1.9, .42, .85, 0x2bb3a3, .2, .21, -1.55); box(1.9, .55, .22, 0x239a8c, .2, .69, -1.9); box(.22, .6, .85, 0x239a8c, -.86, .3, -1.55); box(.22, .6, .85, 0x239a8c, 1.26, .3, -1.55);
  box(.9, .62, .05, 0xffc400, .2, 1.75, -1.98); box(.8, .36, .55, 0x8a5a3c, .2, .18, .1);
  part(new THREE.CylinderGeometry(.2, .15, .38, 24), toon(0xc8643c), -1.55, .19, -1.55); part(new THREE.SphereGeometry(.38, 24, 16), toon(0x3fbf6f), -1.55, .72, -1.55);
  const accent = theme("--gold");
  const bands = [[4, .7, 0, -1.65], [.7, 2.6, -1.65, 0], [4, .7, 0, 1.65], [.7, 2.6, 1.65, 0]].map(([w, d, x, z]) => box(w, .2, d, 0xffffff, x, 2.7, z));
  const leds = [[2.6, .04, 0, -1.29], [.04, 2.6, -1.29, 0], [2.6, .04, 0, 1.29], [.04, 2.6, 1.29, 0]].map(([w, d, x, z]) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, .05, d), new THREE.MeshBasicMaterial({ color: 0x222222 })); m.position.set(x, 2.585, z); room.add(m); return m; });
  const glows = [[0, -1], [-1, 0], [0, 1], [1, 0]].map(([x, z]) => { const l = new THREE.PointLight(accent, 0, 0, 2); l.position.set(x, 2.2, z); room.add(l); return l; });
  const spots = [[-.55, -.55], [.55, -.55], [-.55, .55], [.55, .55]].map(([x, z]) => {
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(.1, .1, .03, 24), new THREE.MeshBasicMaterial({ color: 0x555555 })); disc.position.set(x, 2.785, z); room.add(disc);
    const s = new THREE.SpotLight(0xfff1d6, 0, 0, .5, .35, 1.5); s.position.set(x, 2.75, z); s.target.position.set(x, 0, z); room.add(s, s.target); return { disc, s }; });
  const hemi = new THREE.HemisphereLight(0x9fb4ff, 0x3a2a20, 1.1), sun = new THREE.DirectionalLight(0xffffff, .8); sun.position.set(3, 5, 4); scene.add(hemi, sun);
  const warm = new THREE.Color(0xffe0b0), cool = new THREE.Color(0x9fb4ff), L = sc.lines || [];
  const shade = div("", "", root, "position:absolute;inset:0;pointer-events:none;background:linear-gradient(to bottom,color-mix(in srgb,var(--royal) 80%,transparent) 0%,transparent 30%,transparent 72%,color-mix(in srgb,var(--royal) 70%,transparent) 100%)");
  const l1 = L[0] ? div("", L[0], root, `position:absolute;left:${14 * u}px;right:${14 * u}px;top:${H * .1}px;text-align:center;font:400 ${64 * u}px/1 Anton,Impact,sans-serif;color:var(--gold);text-transform:uppercase`) : null;
  const l2 = L[1] ? div("", L[1], root, `position:absolute;left:${14 * u}px;right:${14 * u}px;top:${H * .1}px;text-align:center;font:400 ${34 * u}px/1.05 Anton,Impact,sans-serif;color:var(--fg);text-transform:uppercase`) : null;
  const show = (e, a) => { if (e) { e.style.opacity = a; e.style.transform = `translateY(${(1 - a) * 24 * u}px) scale(${.92 + .08 * a})`; } };
  return {
    draw(t, dur) {
      const k = dur / 10, T = x => x * k;   // le scénario est écrit pour 10 s, étiré ou resserré à la durée de la scène
      room.scale.setScalar(Math.max(1e-4, back(seg(t, T(.2), T(1)))));
      const d = io(seg(t, T(1.5), T(3.6))), drift = seg(t, T(3.6), dur), a = THREE.MathUtils.degToRad(45 + 5 * d + 10 * drift), rr = 13 - 8.8 * d - .4 * drift;
      cam.position.set(Math.sin(a) * rr, 2.4 - 1.4 * d, Math.cos(a) * rr); cam.lookAt(-.3 * d, 1.3 + 1.1 * d, -.3 * d);
      bands.forEach((g, i) => {   // les caissons jaillissent du plafond, étirés, puis rebondissent
        const s = T(2.6 + i * .35), p = seg(t, s, s + T(.25)), q = seg(t, s + T(.25), s + T(.9)); g.visible = t >= s;
        const sy = p < 1 ? .05 + 1.35 * p : 1 + .4 * Math.exp(-5 * q) * Math.cos(13 * q), sx = p < 1 ? .6 + .4 * p : 1 - .15 * Math.exp(-5 * q) * Math.cos(13 * q);
        g.scale.set(sx, sy, sx); g.position.y = 2.8 - .1 * sy; });
      const led = out(seg(t, T(4.4), T(5.4)));
      leds.forEach(m => m.material.color.setRGB(.13, .13, .13).lerp(accent, led)); glows.forEach(l => { l.intensity = .3 * led; });
      spots.forEach(({ disc, s }, i) => { const q = out(seg(t, T(5.5 + i * .3), T(5.75 + i * .3))); s.intensity = 9 * q; disc.material.color.setRGB(.33 + .67 * q, .33 + .62 * q, .33 + .5 * q); });
      hemi.color.copy(cool).lerp(warm, .6 * led); hemi.intensity = 1.1 - .1 * led; sun.intensity = .8 - .45 * led;
      r.render(scene, cam);
      shade.style.opacity = 1; show(l1, back(seg(t, T(.4), T(.9))) * (l2 ? 1 - seg(t, T(3.6), T(3.9)) : 1)); show(l2, out(seg(t, T(4.6), T(5.3))));
    },
    dispose,
  };
}

export function create(sc, root, u) {
  return sc.type === "room3d" ? room(sc, root, u) : layers(sc, root, u);
}
