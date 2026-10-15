# Studio vidéo (universel)

**Parcours** : Paramètres › Site › « Studio vidéo » → décrire la vidéo voulue en une phrase + choisir le format (vertical 9:16, horizontal 16:9, carré 1:1) →
*Proposer un scénario* (Claude, `video_studio.plan`) → relire la liste des scènes → *Lancer la fabrication* (clic du patron) → GitHub Actions `video.yml` filme et monte
(Chrome + ffmpeg, `scripts/video/`) → *Récupérer la vidéo* (rangée comme document, téléchargeable et partageable). Vidéo muette ; le temps de fabrication varie selon la durée et la complexité.

**Scènes disponibles** : `title` (titre animé), `text` (titre + puces), `photo` (photo avec zoom lent + légende), `gallery` (2 à 6 photos enchaînées), `stats` (chiffres qui montent),
`quote` (avis client), `page` (défilement fluide d'une page du site avec caméra et pastilles de chapitre), `outro` (carte de fin : devis, téléphone, site). Une vidéo = jusqu’à 50 scènes, 150 s (2 minutes 30) au plus pour le moment. La consigne peut contenir jusqu’à 20 000 caractères. Après optimisation à 30 i/s, un rendu réel de référence de 45,7 s a été fabriqué en environ 6 minutes sur GitHub Actions. Le plafond est relevé prudemment à 150 s (2 minutes 30) ; le temps dépend du nombre et du type de scènes. Il faudra mesurer des rendus plus longs avant de relever encore cette limite. Au-delà de ces limites, le moteur refuse explicitement la demande au lieu de supprimer silencieusement des scènes.

**Clip IA court** : le même Studio propose aussi une génération réelle via Higgsfield / Wan 3.0 Prime, de 2 à 30 secondes en 720p, format vertical/horizontal/carré et son IA facultatif. Le clip est généré après confirmation, consomme des crédits Higgsfield payants et la limite de sécurité est d'un clip par jour. Une fois terminé, il est rangé dans Documents. Cette fonction ne remplace pas encore le montage scénarisé de 150 secondes : les clips IA courts et le montage long sont deux parcours séparés.

**Pourquoi GitHub Actions** : filmer image par image demande Chrome, ffmpeg et plusieurs processeurs ; le conteneur Render ne s'y prête pas.
**Garde-fous** : Claude choisit parmi des CATALOGUES (`video_studio.py` : photos du site, chiffres vrais `FACT_STATS`, avis réels `QUOTES`, pages `PAGES`) et rédige seulement titres, légendes et puces ;
téléphone et site viennent de `FACTS`. Le scénario est reconstruit côté serveur au lancement (`build_spec`) puis revalidé par `scripts/video/spec.py` (photos du site seulement, adresses unicplaquiste.com / aperçus
Netlify seulement, sélecteurs `#id`/`.classe` simples). Rien n'est publié. Test du contrat serveur ↔ moteur et des nouvelles limites : `backend/tests/test_video_studio.py`.
**Prérequis** : jeton GitHub de l'Atelier avec « Actions : Read and write » ; `video.yml` sur la branche principale.

**Étendre** : un nouveau chiffre vrai → `FACT_STATS` ; un nouvel avis → `QUOTES` ; une nouvelle page filmable → `PAGES` (adresse + chapitres `#id`) ; un nouveau type de scène → `scripts/video/spec.py`
(validation) + `scenes.html` (animation) + `video_studio.py` (catalogue). Photos : celles du dossier `images/` du site (liste lue sur le dépôt du site si connecté, sinon liste de secours).
**Pas encore** : voix off narrée et synchronisée dans le montage scénarisé long ; les clips courts générés par IA peuvent avoir leur propre son. Photos prises depuis l'appli (il faudrait les héberger), vidéo d'un site tiers.

**Moteur** (`overlay.html` / `overlay.mjs` : ancien moteur du portfolio, conservés et inutilisés) : `make.py` → `render.mjs` (scène page : capture déterministe, horloge virtuelle, animations CSS pilotées à la main, défilement au pixel physique) + `scenes.mjs` (scènes HTML et pastilles, image par image)
→ `compose.py` (caméra sous-pixel, 30 i/s par défaut sans mélange d'images, fondus de raccord, sortie ≤ 25 Mo). Cadence configurable : `VIDEO_FPS=24`, `30` (défaut) ou `60`. Essai local : `VIDEO_ALLOW_LOCAL=1 python scripts/video/make.py scripts/video/sample.json sortie.mp4`.
