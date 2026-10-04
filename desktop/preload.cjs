const { contextBridge } = require("electron");

// Seul signal exposé à la page : « je suis l'application PC ». Aucun accès Node.
contextBridge.exposeInMainWorld("unicDesktop", true);
