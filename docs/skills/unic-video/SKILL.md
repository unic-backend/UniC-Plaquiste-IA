---
name: unic-video
description: Montage vidéo UniC Plaquiste à partir des vraies vidéos et photos de chantier (Reels, TikTok, YouTube, présentation client) avec le moteur du dépôt (scripts/video, Chrome + ffmpeg). À utiliser dès que le patron demande une vidéo, un montage, un Reel, un TikTok, un avant/après filmé ou une vidéo de présentation. Ne tourne jamais tout seul : seulement à la demande.
---

# Vidéos UniC (à la demande)

## 1. Comprendre la demande
Sujet, durée, format (vertical 9:16 pour Reels/TikTok, horizontal 16:9 pour YouTube, carré 1:1), textes voulus, musique ou non (le montage est muet par défaut), voix off ou non (voix française gratuite : recette « Voix off » de `docs/VIDEO-RECETTES.md`).
Une info manque : UNE question courte.

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

## Interdits
Rien n'est publié ni envoyé sans le clic du patron. Pas d'image d'un autre compte. Pas de crédit Higgsfield dépensé sans sa confirmation.
