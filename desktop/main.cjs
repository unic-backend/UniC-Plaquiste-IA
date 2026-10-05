// UniC AI pour PC : fenêtre Electron qui sert l'interface embarquée (unic://app) ; l'API reste sur le serveur UniC.
const { app, BrowserWindow, protocol, net, shell, session, ipcMain, safeStorage } = require("electron");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const DIST = app.isPackaged ? path.join(process.resourcesPath, "app-dist") : path.join(__dirname, "..", "frontend", "dist");
const ORIGIN = "unic://app";

protocol.registerSchemesAsPrivileged([
  { scheme: "unic", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

if (!app.requestSingleInstanceLock()) app.quit();

function serve(request) {
  const url = new URL(request.url);
  let file = path.normalize(path.join(DIST, decodeURIComponent(url.pathname)));
  const inside = file === DIST || file.startsWith(DIST + path.sep);
  if (!inside || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, "index.html");   // routes de l'appli
  return net.fetch(pathToFileURL(file).toString());
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 420, minHeight: 600, backgroundColor: "#1A2320", title: "UniC AI",
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {   // liens externes : navigateur, jamais dans l'appli
    if (/^https:\/\//i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(ORIGIN)) {
      e.preventDefault();
      if (/^https:\/\//i.test(url)) shell.openExternal(url);
    }
  });
  win.loadURL(ORIGIN + "/");
}

// ---------- Moteur local : le PC répond quand Claude est indisponible (Ollama sur ce PC) ----------
// Le PC va chercher le travail sur le serveur : rien à ouvrir sur la box, aucun port exposé.
const OLLAMA = "http://127.0.0.1:11434";
const DEFAULT_MODEL = process.env.UNIC_LOCAL_MODEL || "qwen2.5:7b";
const cfgFile = () => path.join(app.getPath("userData"), "worker.json");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readCfg() {
  try {
    const raw = JSON.parse(fs.readFileSync(cfgFile(), "utf8"));
    const code = raw.enc && safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(Buffer.from(raw.code, "base64")) : raw.code;
    return { server: raw.server || "", code: code || "", model: raw.model || DEFAULT_MODEL };
  } catch { return { server: "", code: "", model: DEFAULT_MODEL }; }
}

function saveCfg(server, code) {
  if (!/^https:\/\//i.test(server) || !code) return;
  const enc = safeStorage.isEncryptionAvailable();   // code d'accès chiffré par Windows (DPAPI)
  const stored = enc ? safeStorage.encryptString(code).toString("base64") : code;
  fs.writeFileSync(cfgFile(), JSON.stringify({ server: server.replace(/\/+$/, ""), code: stored, enc, model: readCfg().model }));
}

async function localModel(wanted) {
  const r = await fetch(`${OLLAMA}/api/tags`);
  const names = ((await r.json()).models || []).map((m) => m.name);
  if (!names.length) return null;
  return names.includes(wanted) ? wanted : names.find((n) => n.startsWith(wanted.split(":")[0])) || names[0];
}

async function workerLoop() {
  for (;;) {
    const cfg = readCfg();
    if (!cfg.server) { await sleep(10000); continue; }
    let model = null;
    try { model = await localModel(cfg.model); } catch { model = null; }
    if (!model) { await sleep(30000); continue; }   // Ollama absent : le serveur voit le PC hors ligne
    const headers = { "Content-Type": "application/json", "X-Access-Code": cfg.code };
    try {
      const r = await fetch(`${cfg.server}/api/worker/poll`, { method: "POST", headers, body: JSON.stringify({ model }) });
      if (!r.ok) { await sleep(15000); continue; }
      const { job } = await r.json();
      if (!job) continue;
      let text = "", ok = true;
      try {
        const o = await fetch(`${OLLAMA}/api/chat`, { method: "POST", body: JSON.stringify({
          model, messages: job.messages, stream: false, options: { temperature: 0.2, num_ctx: 8192 } }) });
        text = ((await o.json()).message || {}).content || "";
      } catch { ok = false; }
      await fetch(`${cfg.server}/api/worker/result/${job.id}`, { method: "POST", headers,
        body: JSON.stringify({ text, model, ok: ok && !!text }) });
    } catch { await sleep(10000); }
  }
}

ipcMain.on("unic:worker-config", (_e, { server, code }) => { try { saveCfg(server, code); } catch { /* ignoré */ } });

app.whenReady().then(() => {
  workerLoop();
  protocol.handle("unic", serve);
  session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) =>
    cb(["media", "clipboard-sanitized-write", "notifications"].includes(permission)));
  createWindow();
  app.on("activate", () => BrowserWindow.getAllWindows().length === 0 && createWindow());
});
app.on("second-instance", () => {
  const [w] = BrowserWindow.getAllWindows();
  if (w) { if (w.isMinimized()) w.restore(); w.focus(); }
});
app.on("window-all-closed", () => app.quit());
