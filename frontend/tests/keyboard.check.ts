// Clavier du téléphone : le champ où l'on tape doit rester visible au-dessus du clavier, sur tous les écrans. Lancer : npm run test:phone
import { keyboardInset, revealDelta } from "../src/keyboard";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };
// écran 800 px, clavier 340 px : partie visible 0 → 460
eq("champ caché sous le clavier : on descend juste assez", revealDelta(600, 650, 0, 460), 202);
eq("champ déjà visible : rien", revealDelta(100, 150, 0, 460), 0);
eq("champ au-dessus de la partie visible : on remonte", revealDelta(-80, -30, 0, 460), -92);
eq("grand champ (studio) : on montre son haut", revealDelta(500, 900, 0, 460), 488);
eq("pas de place : rien", revealDelta(10, 20, 300, 300), 0);
// mesure par visualViewport (navigateur) : inchangée
eq("clavier mesuré", keyboardInset(800, 460, 0), 340);
eq("barre d'adresse : pas un clavier", keyboardInset(800, 760, 0), 0);
eq("zoom au doigt : rien", keyboardInset(800, 400, 0, 2), 0);
console.log(`clavier : ${ok} OK, ${ko} échec(s)`);
if (ko) process.exit(1);
