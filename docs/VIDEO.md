# Vidéo du portfolio

**Parcours** : Paramètres › Site › « Vidéo du portfolio » → *Proposer un scénario* (Claude, via `video_studio.plan`) → *Lancer la fabrication* (clic du patron) → GitHub Actions `video.yml`
filme la page (Chrome + ffmpeg, `scripts/video/`) → *Récupérer la vidéo* (rangée comme document, téléchargeable et partageable).

**Pourquoi GitHub Actions** : filmer image par image demande Chrome, ffmpeg et plusieurs processeurs pendant 15 à 20 minutes ; le conteneur Render ne s'y prête pas.
**Garde-fous** : Claude choisit seulement l'ordre, la durée et des titres dans un CATALOGUE (`video_studio.CATALOG`) ; adresse, sélecteurs, téléphone et site viennent du code.
Le scénario est reconstruit côté serveur au lancement, puis revalidé par `scripts/video/spec.py` (seuls unicplaquiste.com et les aperçus Netlify sont filmables). Rien n'est publié.
**Prérequis** : jeton GitHub de l'Atelier avec « Actions : Read and write » ; `video.yml` fusionné sur la branche principale (sans quoi GitHub refuse le lancement).
**Ajouter une page** : une entrée dans `CATALOG` (adresse + sélecteurs `#id`) et dans l'énumération de l'outil `storyboard`.
**Moteur** : `render.mjs` (capture déterministe : horloge virtuelle, animations CSS pilotées à la main, défilement au pixel physique) → `overlay.mjs` (ouverture, chapitres, fin) → `compose.py`
(caméra sous-pixel, 60 i/s sans mélange d'images, sortie ≤ 25 Mo). Essai local : `VIDEO_ALLOW_LOCAL=1 python scripts/video/make.py spec.json sortie.mp4`.
