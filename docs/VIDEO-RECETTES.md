# Recettes vidéo (atelier de montage de Claude)

Ce que Claude a appris le 04/11/2026 à partir des vidéos et des dépôts donnés par le patron, testé sur une machine **sans carte graphique**
(4 processeurs, 15 Go). Complète `docs/VIDEO.md` (Studio vidéo de l'appli) : ici, ce sont les outils et modèles de l'atelier, utilisés par Claude.
Rien n'est publié : les vidéos sont livrées au patron, qui décide.

## Modèles prêts (`scripts/video/modeles/`)
Rendu : `bash scripts/video/modeles/preparer.sh <modèle> [sortie.mp4]` (1080×1920, 30 i/s ; télécharge une fois les outils dans `~/.cache/unic-video`).

| Modèle | Style (vidéo de référence) | Durée | Contenu |
|---|---|---|---|
| `cloison` | vue éclatée 3D (« breakdown », V2) | 9 s | Cloison 72/48 : rails 48, montants tous les 60 cm, laine 45 mm, BA13 12,5 mm, bandes + enduit, légendes reliées |
| `plafond` | scène 3D décorative (V4) | 9 s | Salon le soir : la LED de la gorge fait le tour, puis les spots s'allument |
| `devis` | explication animée en cartes (V1) | 16 s | « Votre devis en 3 étapes » : WhatsApp, visite et métré à Dakar, devis gratuit sous 48 h, 8 ans / 180+ / 98 % |
| `references` | vitrine de chantiers | 16 s | Stade Abdoulaye Wade, Dakar Arena, UAM, Centre équestre (photos du site), signature avec le numéro |
| `etapes` | trait minimaliste (« /minimalistic-graphics », V2) | 10 s | Barres au trait : tracé, ossature, plaques, joints, peinture ; un point d'or monte de l'une à l'autre |
| `points` | grille de points (V2) | 11 s | 180 points = 180+ chantiers livrés ; le compteur compte les points allumés ; les 4 grands projets en or |
| `bonhomme` | histoire en bonhomme bâton (« /stick-figure », V2) | 12 s | Pièce nue → message à UniC (« devis gratuit sous 48 h ») → le plaquiste arrive → la plaque devient un faux plafond LED |
| `trajet` | trajet sur carte (« /map-route », V2) | 11 s | Dakar → Diamniadio sur la vraie côte (Natural Earth, domaine public), 28 km à vol d'oiseau, les 4 grands projets |
| `etsi` | 3D cartoon « et si ? » (V2) | 10 s | Maquette de salon (contours noirs, 3 tons) ; la caméra entre, les caissons jaillissent du plafond, la LED puis les spots s'allument |

Chiffres et coordonnées = ceux de `FACTS` / `FACT_STATS` (`backend/app/video_studio.py`) ; photos = dossier `images/` du site.

**Créer un modèle** : une page HTML 1080×1920 avec un élément racine `data-composition-id="main" data-duration="…"`, une timeline GSAP en pause
enregistrée dans `window.__timelines["main"]`, et pour la 3D un `renderAt(t)` appelé par l'évènement `hf-seek` (`e.detail.time`).
Tout doit dépendre du temps `t` seulement (pas d'horloge, pas de hasard non fixé) : HyperFrames filme les images dans le désordre.
Bibliothèques et polices en local (`lib/`, `fonts/`, copiées par `preparer.sh`), jamais depuis un CDN.
Un trait qui se dessine : `pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"`, animé par `attr: { "stroke-dashoffset": 0 }`
(animé en style, GSAP arrondit les px et le trait apparaît d'un coup). Un compteur suit le même temps que ce qu'il compte (`onUpdate`).
Vérifier avant de rendre : `hyperframes lint`, puis `hyperframes snapshot --at 1.2,4.5,…` et regarder les images.
`backend/tests/test_video_modeles.py` refuse un modèle qui charge quelque chose depuis Internet ou qui dépend de l'horloge ou du hasard.

## Recettes testées
| Besoin | Outil (licence) | Commande / point clé |
|---|---|---|
| Sous-titres mot à mot, mot dit en jaune | faster-whisper (MIT) + `scripts/video/captions.py` | modèle `small`, `language="fr"`, `word_timestamps=True` → `mots.json` → `python scripts/video/captions.py mots.json st.ass 1080 1920` → `ffmpeg -i v.mp4 -vf ass=st.ass` |
| Effets sur une vidéo face caméra (texte derrière la tête, graphique en verre, liste cochée…) | claude-video-effects (MIT, 51 effets) | `scripts/setup.sh` puis `fx.py --plan plan.json video.mp4 sortie.mp4` ; besoin de `libegl1` ; une vidéo du patron filmée de face |
| Couper sur le rythme de la musique | librosa (ISC) | `librosa.beat.beat_track` → temps forts |
| Trouver les plans d'une vidéo | PySceneDetect (BSD) | `detect(video, ContentDetector())` |
| Détourer une personne sans fond vert | rembg (MIT) | modèle `u2net_human_seg` |
| Couper les silences | auto-editor (Unlicense) | `--edit audio:threshold=0.04 --margin 0.15sec` |
| Vidéos de référence | yt-dlp (Unlicense) | `--js-runtimes node` ; une vidéo de tiers sert à étudier, jamais à republier |
| Stabiliser, ralentir, niveau sonore | FFmpeg (déjà là) | filtres `vidstabdetect/vidstabtransform`, `minterpolate`, `loudnorm` |

## Maîtrise universelle (règle du patron : tous les domaines, pas seulement le placo)
Chaque style se choisit d'après ce qu'il faut MONTRER, jamais d'après le métier. Même outil, autre domaine :

| Domaine | Montrer | Outil (Studio de l'appli / atelier) |
|---|---|---|
| Trading, commerce, ventes | une évolution, un écart | `chart` (courbe + %), `counter`, `stats` |
| Agriculture | ce dont un sol ou une plante est fait ; une saison | `layers3d` (horizons du sol), `bars` (semis → récolte), `chart` (rendement) |
| Élevage, pêche | un effectif ; un cycle de vie ; une zone | `dots` (un point par bête), `bars` (œuf → adulte), `route` (sortie en mer) |
| Informatique, technologie | du code, une architecture | `code` (éditeur qui se tape), `layers3d` (couches d'une application), `flow` |
| Logistique, export | un trajet, des étapes | `route`, `flow`, `counter` (délais) |
| Sport | une équipe, un score, une progression | `dots` (joueurs), `chart` (buts, temps), `stats` |
| Intérieur, déco, BTP | un ouvrage, une ambiance | `layers3d`, `room3d`, modèles `cloison` et `plafond` |

Vérité partout : un chiffre vient de la demande ou d'une source sûre ; s'il illustre seulement, le mot « exemple » est écrit à l'écran.

## Règles de qualité retenues
- **Vrai** : jamais d'avis, de chiffre, de chantier ou de garantie inventés ; un exemple est marqué « exemple ».
- **Compréhensible sans le son** : à la fin, on sait ce que fait UniC et quoi faire (devis, WhatsApp).
- **Juger chaque rendu** sur des images arrêtées avant de livrer : texte qui touche le titre, flèche qui vise la mauvaise pièce, contraste (blanc sur jaune illisible), accents coupés, virgule décimale française.
- **Mise en scène** : un sujet qui remplit 60 à 85 % du cadre ; une idée par plan ; 3D seulement quand elle explique (vue éclatée, lumière) ; légendes rangées en colonne sans traits qui se croisent.
- **Lumière 3D** sans carte graphique : panneaux lumineux (`RectAreaLight`) pour une gorge LED, lumière qui rebondit (hémisphère chaude) sinon le plafond reste noir.

## Écartés (et pourquoi)
- Usage commercial interdit : video-talkcraft, anything2explainer (PolyForm Noncommercial), video-editor-skills (DaVinci payant, non commercial).
- Remotion : licence payante au-delà de 3 personnes dans l'entreprise. OpenMontage (AGPL) : lu pour apprendre, aucun code repris.
- Carte graphique nécessaire : ComfyUI, FreeVideo, Real-ESRGAN, RIFE. Applications à écran : Audacity, Subtitle Edit, OpenToonz, Penpot, cables.gl.
- Voix off (Chatterbox, Qwen3-TTS) : possible mais très lent sans carte graphique, pas encore testé.

## Garder l'atelier d'une session à l'autre
La machine de Claude est effacée entre deux sessions. Script à coller une fois par le patron dans les réglages de l'environnement
(menu de l'environnement › Modifier › Script d'installation) :
```bash
apt-get install -y -q --no-install-recommends libegl1 libgles2 libgl1 || true
python3 -m venv /opt/atelier-video
/opt/atelier-video/bin/pip install -q faster-whisper==1.2.1 librosa==0.11.0 scenedetect==0.7.2 auto-editor==29.3.1 \
  "rembg[cpu]==2.0.69" color-matcher==0.6.0 yt-dlp==2026.10.26 pillow==10.4.0
npm install --prefix "$HOME/.cache/unic-video" --no-save --silent hyperframes@0.8.179 three@0.187.0 gsap@3.15.1 \
  @fontsource/anton@5.3.0 @fontsource/inter@5.3.0
git clone -q --depth 1 https://github.com/Vibha-Ramprakash/claude-video-effects /opt/atelier-video/effects \
  && bash /opt/atelier-video/effects/scripts/setup.sh
```
HyperFrames : toujours `HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1` (statistiques coupées) et jamais `hyperframes publish`.

## Pas encore
Voix off générée ; ces modèles dans le Studio de l'appli (il faudrait installer HyperFrames dans `.github/workflows/video.yml`, zone protégée : décision du patron) ;
Blender ; une vraie vidéo du patron face caméra pour les effets.
