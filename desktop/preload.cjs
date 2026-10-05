const { contextBridge, ipcRenderer } = require("electron");

// Seul pont exposé à la page : « je suis l'application PC » + transmettre le serveur et le code au moteur local du PC.
contextBridge.exposeInMainWorld("unicDesktop", {
  desktop: true,
  configureWorker: (server, code) => ipcRenderer.send("unic:worker-config", { server: String(server || ""), code: String(code || "") }),
});
