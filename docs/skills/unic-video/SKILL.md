---
name: unic-video
description: Vidéos pour UniC Plaquiste ou personnelles du patron (Reels, TikTok, YouTube, présentation client, documentaire, pub de produit, vidéo « comme cette référence ») à partir de ses vrais médias avec le moteur du dépôt (scripts/video, Chrome + ffmpeg). À utiliser dès que le patron demande une vidéo, un montage, un Reel, un TikTok, un avant/après filmé ou une vidéo de présentation. Ne tourne jamais tout seul : seulement à la demande.
---

# Vidéos UniC (à la demande)

## 1. Comprendre la demande
Sujet, durée, format (vertical 9:16 pour Reels/TikTok, horizontal 16:9 pour YouTube, carré 1:1), textes voulus, musique ou non (le montage est muet par défaut), voix off ou non (voix française gratuite : recette « Voix off » de `docs/VIDEO-RECETTES.md`).
Une info manque : UNE question courte.

## 1 bis. « Comme cette vidéo » ou un style demandé
1. Étudie la référence image par image : `python scripts/video/etudier.py ref.mp4 dossier` (4 images/s) et regarde TOUTES les planches. Jamais de survol.
2. Écris UN brief (sujet, format, durée, style vu, faits vrais, interdits) et fabrique à partir de lui, pas du fil de la discussion.
3. Styles prêts (`scripts/video/modeles/`, tableau de `docs/VIDEO-RECETTES.md`) : `enquete` (documentaire collage), `produit` (pub d'appli), `references`, `devis`, `cloison`, `plafond`, `points`, `etapes`, `trajet`, `bonhomme`, `etsi`. Copie le plus proche et change textes, photos, durées.
4. Contrôle : `UNIC_VIDEO_IMAGES="1,4,9" bash scripts/video/modeles/preparer.sh <modèle> dossier` (images arrêtées), puis rendu, puis `etudier.py sortie.mp4 dossier 2`.
5. Défauts = liste numérotée ; corrige seulement la liste, garde le reste.
Vidéo personnelle (famille, fête, sport, autre métier) : même méthode ; pas de logo ni de téléphone UniC sauf demande.

## 2. Médias
- Drive « UniC Plaquiste — Portfolio Ousmane Diop » (id `1NTtF0hVYhnSk5H8zeZgm-BWQw47C38wp`) : `02_Photos_Chantiers`, `03_Videos_Chantiers`.
- Télécharge les fichiers choisis (connecteur Google Drive) dans un dossier de travail du scratchpad. Regarde une image de chaque clip (`ffmpeg -ss 2 -i clip.mp4 -frames:v 1 f.jpg`) pour vérifier que c'est bien un chantier UniC. Un fichier qui porte le pseudo d'une autre marque = exclu.
- Images générées par IA (Higgsfield) : payantes, seulement si le patron les demande et confirme le nombre.

## 3. Scénario (`spec.json`, format de `scripts/video/spec.py`, exemple : `scripts/video/sample.json`)
Scènes utiles : `title`, `clip` (vrai film : `url`, `start`, `seconds`, `overlay`, vitesse, étalonnage, zoom), `photo`, `gallery`, `text`, `stats` (chiffres VRAIS seulement), `outro` (devis, +221 77 708 50 92, unicplaquiste.com).
Règles (docs/VIDEO.md) : accroche dans les 3 premières secondes, une idée par scène, fin qui conclut. Jamais de prix, de faux chiffre ni de client nommé sans accord.

## 4. Rendu local (testé dans une session Claude Code)
```bash
cd scripts/video && mkdir -p node_modules && ln -sfn "$(dirname "$(node -e "console.log(require.resolve('playwright'))")")" node_modules/playwright && cd ../..
(cd DOSSIER_MEDIAS && python3 -m http.server 8765 &)        # les clips deviennent http://localhost:8765/nom.mp4
VIDEO_ALLOW_LOCAL=1 python3 scripts/video/make.py spec.json sortie.mp4   # "fps": 24 dans le spec pour aller plus vite
```
`node_modules` est ignoré par git. Vérifie le résultat : durée (`ffprobe`), 2 ou 3 images extraites et regardées.

## 5. Livrer
- Envoie la vidéo au patron (fichier) et range-la dans le Drive (dossier `04_Videos_Chantiers`).
- S'il le demande : publication EN ATTENTE DE VALIDATION dans Metricool (`createScheduledPostForReview`), jamais de publication directe.

## Travail fini (à cocher avant de rendre, sinon on corrige d'abord)
- [ ] Référence donnée : toutes les planches regardées avant le brief ; lignes de 2 à 7 mots, aucune formule creuse.
- [ ] Accroche dans les 3 premières secondes ; format demandé (9:16, 16:9 ou 1:1).
- [ ] Seulement de vrais médias UniC ; aucun prix, faux chiffre ou client nommé sans accord.
- [ ] Durée vérifiée (`ffprobe`) et 2 ou 3 images regardées ; voix off réécoutée si présente.
- [ ] Fin avec contact (+221 77 708 50 92) ; rien publié sans le clic du patron.

## Règle d'or
Une erreur signalée par le patron se corrige dans CE mode d'emploi (branche + PR), pas seulement dans le chat : sinon elle revient.

## Interdits
Rien n'est publié ni envoyé sans le clic du patron. Pas d'image d'un autre compte. Pas de crédit Higgsfield dépensé sans sa confirmation.
