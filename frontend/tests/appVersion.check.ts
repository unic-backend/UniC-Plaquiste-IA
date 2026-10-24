// Nouvelle version : l'appli du téléphone compare son interface à celle du serveur. Lancer : npm run test:phone
import { updateNeeded } from "../src/appVersion";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };

eq("même interface : rien", updateNeeded("a1b2c3d4e5f6", "a1b2c3d4e5f6", null), false);
eq("serveur plus récent : bandeau", updateNeeded("a1b2c3d4e5f6", "0f9e8d7c6b5a", null), true);
eq("mise de côté par le patron : plus de bandeau pour CETTE version", updateNeeded("a1b2c3d4e5f6", "0f9e8d7c6b5a", "0f9e8d7c6b5a"), false);
eq("version suivante après une mise de côté : bandeau", updateNeeded("a1b2c3d4e5f6", "111111111111", "0f9e8d7c6b5a"), true);
eq("serveur sans interface compilée : rien", updateNeeded("a1b2c3d4e5f6", undefined, null), false);
eq("réponse bizarre du serveur : rien", updateNeeded("a1b2c3d4e5f6", "<html>", null), false);
eq("appli sans empreinte (développement) : rien", updateNeeded("", "0f9e8d7c6b5a", null), false);
console.log(`appVersion : OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
