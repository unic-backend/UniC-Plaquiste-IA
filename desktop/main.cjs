// UniC AI pour PC : fenêtre Electron qui sert l'interface embarquée (unic://app) ; l'API reste sur le serveur UniC.
const { app, BrowserWindow, protocol, net, shell, session } = require("electron");
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

app.whenReady().then(() => {
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
