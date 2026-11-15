---
name: unic-croquis
description: Croquis dessinés à la main (moteur Sketchy, MIT) pour expliquer une méthode, un ordre de pose, une comparaison, un cycle ou une chronologie dans un travail important (rapport, document, devis expliqué, cours, vidéo, présentation). À utiliser dès qu'un dessin fait comprendre plus vite qu'un paragraphe. Pas pour un plan coté : là, draw_diagram / un plan.
---

# Croquis UniC (Claude Code et UniC IA)

Tu dis **quoi** dessiner ; le moteur place tout. **Jamais de coordonnées** (sauf dans un bloc `draw`).
Même moteur partout : `frontend/public/vendor/sketchy/sketchy.js` (copie relue, empreinte vérifiée par test).

## Où ça marche
| Endroit | Comment |
|---|---|
| Chat UniC IA | l'IA écrit un bloc ```` ```sketchy ```` ; l'appli le dessine, étapes cliquables (prompt dans `backend/app/agent.py`, « CROQUIS EXPLICATIF ») |
| Formation UniC | champ `croquis` d'une leçon dans `backend/app/formation.py` |
| Claude Code : rapport, document, vidéo | `node scripts/croquis.mjs scene.txt dossier/` → `croquis.png`, `etape-1.png`…, `croquis.svg`, `croquis.html` (+ `sketchy.js`, interactif, sans Internet), `etapes.json` |

- **Rapport / document (docx, pdf, page)** : insère `croquis.png` (ou `croquis.svg`) ; pour un pas-à-pas, les `etape-N.png` avec le texte de `etapes.json`.
- **Vidéo** : une scène par idée ; chaque `etape-N.png` est une image de la vidéo (le rouge entoure ce que dit la voix), dans un modèle de `scripts/video/modeles/` en `<img>`. Pour une vidéo 1080 : `--echelle 4` (images nettes) ; la caméra peut viser la boîte rouge de chaque étape (repérée sur l'image, pixels rouges).
- **Partage** : envoyer le dossier `croquis.html` + `sketchy.js` (s'ouvre dans un navigateur, cliquable).

## Syntaxe (une ligne par élément)
```
title <texte>            subtitle <texte>            dir right|down
group <id> <libellé>
<id> <libellé 1-4 mots> [(cylinder|person|note|circle|rounded)] [in <group>] [!accent|!muted] [~ détail au survol]
<a> -> <b> [libellé]     (--> pointillé, <-> double)
step <titre>: <phrase> | <ids à entourer ; flèches a->b>
```
Formes prêtes (une entrée par ligne, ligne vide à la fin) : `timeline t: Titre` (`<quand> | <quoi>`), `cycle c: Titre`, `pyramid p:`, `funnel f:`,
`mindmap m:` (`centre`, `- branche`, `-- sous-branche`), `venn v:` (`set a X`, `set b Y`, `a,b | commun`), `matrix x:` (`cols A | B` puis lignes).
Dessin libre : `draw <id> [LxH] : titre` puis `circle x,y r`, `rect x,y w h`, `line x,y x,y`, `measure x,y x,y` (cote), `object house|person|… x,y`.
Détail complet : `frontend/public/vendor/sketchy/README.md` renvoie au dépôt ddkbs/sketchy (skill/SKILL.md).

## Règles de qualité
- Un seul schéma par idée : structure (de quoi c'est fait), flux (comment ça marche + étapes), comparaison (2 groupes parallèles), cycle, chronologie.
- 3 à 10 éléments ; `!accent` sur 1 seul ; libellés de 1 à 4 mots, le détail après `~`.
- 3 à 6 étapes, une idée chacune.
- Règles métier : seulement celles de la mémoire / Banque de règles (rien d'inventé, aucune cote inventée). Pas de nom de client.
- Vérifie toujours l'image produite avant de la livrer (Read sur le PNG).

## Exemple vérifié
```
title Pose d'un faux plafond
dir right
trace Tracer le niveau ~ laser ou cordeau
corniere Cornières ~ 1 cheville tous les 30 cm
tige Tiges ~ 0,30 m du mur, puis 0,90 m
fourrure Fourrures !accent ~ tous les 0,50 m
plaque Plaques ~ vissées, 15 vis par m²
trace -> corniere
corniere -> tige
tige -> fourrure
fourrure -> plaque
step Niveau: On trace la hauteur du plafond tout le tour | trace
step Rive: Les cornières suivent le trait | corniere trace->corniere
step Ossature: Tiges puis fourrures | tige fourrure tige->fourrure
step Plaques: On visse les plaques en travers | plaque fourrure->plaque
```

## Limites
- Boutons du moteur en anglais (« Walk through… ») ; les images exportées n'en ont pas.
- Icônes `@…` : chargées sur Internet, bloquées dans l'appli → ne pas en mettre.
- `scripts/croquis.mjs` a besoin de Node et de Playwright (présents dans les sessions Claude Code), pas le serveur Render.
