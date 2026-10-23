// Studio vidéo : durées, chiffres et ambiances de l'aperçu, comme le moteur (scripts/video). Lancer : npm run test:phone
import { duration, frText, sceneSeconds, statNumber, THEMES, totalSeconds } from "../src/videoBoard";
let ok = 0, ko = 0;
const eq = (l: string, g: unknown, w: unknown) => { const a = JSON.stringify(g), b = JSON.stringify(w); (a === b ? ok++ : ko++); if (a !== b) console.log("ÉCHEC", l, a, "≠", b); };

eq("décimales gardées (2,5 % ne devient pas 3 %)", statNumber(2.5), "2,5");
eq("milliers groupés, insécables", statNumber(3900000), "3 900 000");
eq("une année reste lisible", statNumber(1857), "1857");
eq("négatif avec le vrai signe moins", statNumber(-15), "−15");
eq("deux décimales au plus", statNumber(3.14159), "3,14");
eq("pas un nombre : rien", statNumber("abc"), "");
eq("page : accueil + chapitres + descente finale", sceneSeconds({ type: "page", hero_seconds: 4.4, chapters: [{ seconds: 4 }, { seconds: 5 }] }), 15.9);
eq("scène sans durée", sceneSeconds({ type: "title" }), 0);
eq("total arrondi", totalSeconds([{ type: "title", seconds: 3.7 }, { type: "text", seconds: 7.4 }]), 11);
eq("durée courte", duration(42), "42 s");
eq("durée longue", duration(65), "1 min 05 s");
eq("les 6 ambiances du moteur", Object.keys(THEMES).join(","), "unic,night,light,earth,ocean,sunset");
eq("insécables français", frText("Dakar Arena : 15 000 places !"), "Dakar Arena\u00a0: 15\u00a0000 places\u00a0!");
eq("guillemets", frText("« Bonjour »"), "«\u00a0Bonjour\u00a0»");
eq("vide", frText(undefined), "");
console.log(`videoBoard : OK ${ok}  ÉCHECS ${ko}`);
if (ko) process.exit(1);
