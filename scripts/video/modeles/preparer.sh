#!/usr/bin/env bash
# Rend un modèle HyperFrames de scripts/video/modeles en MP4 (vertical 1080×1920), sans rien écrire dans le dépôt.
# Usage : bash scripts/video/modeles/preparer.sh <modèle> [sortie.mp4]   (modèles : les dossiers à côté, voir docs/VIDEO-RECETTES.md)
# Outils (téléchargés une fois dans ~/.cache/unic-video) : HyperFrames (HTML + GSAP filmé image par image), Three.js, GSAP, polices Anton/Inter/Instrument Serif (OFL).
# Photos et logo : ceux du site unicplaquiste.com, rien d'inventé. Jamais « hyperframes publish » : rien ne part sans le clic du patron.
set -euo pipefail
NOM="${1:?modèle : un dossier de scripts/video/modeles (cloison, plafond, devis, references, etapes, points, bonhomme, trajet, etsi, enquete, produit)}"
ICI="$(cd "$(dirname "$0")" && pwd)"
SORTIE="$(realpath -m "${2:-$NOM.mp4}")"
OUTILS="${UNIC_VIDEO_OUTILS:-$HOME/.cache/unic-video}"
SITE="https://www.unicplaquiste.com/images"
[ -f "$ICI/$NOM/index.html" ] || { echo "modèle inconnu : $NOM"; exit 1; }

# Versions figées, publiées depuis plus de deux semaines (04/11/2026).
if [ ! -x "$OUTILS/node_modules/.bin/hyperframes" ] || [ ! -d "$OUTILS/node_modules/@fontsource/instrument-serif" ]; then
  mkdir -p "$OUTILS"
  npm install --prefix "$OUTILS" --no-save --no-audit --no-fund --silent \
    hyperframes@0.8.179 three@0.187.0 gsap@3.15.1 @fontsource/anton@5.3.0 @fontsource/inter@5.3.0 \
    @fontsource/instrument-serif@5.2.8
fi
N="$OUTILS/node_modules"

TRAVAIL="$(mktemp -d)"
trap 'rm -rf "$TRAVAIL"' EXIT
cp -r "$ICI/$NOM" "$TRAVAIL/projet"
cd "$TRAVAIL/projet"
mkdir -p lib fonts assets
cp "$N/gsap/dist/gsap.min.js" "$N/three/build/three.module.js" "$N/three/build/three.core.js" \
   "$N/three/examples/jsm/lights/RectAreaLightUniformsLib.js" "$N/three/examples/jsm/lights/RectAreaLightTexturesLib.js" lib/
cp "$N/@fontsource/anton/files/anton-latin-400-normal.woff2" "$N/@fontsource/inter/files/inter-latin-500-normal.woff2" \
   "$N/@fontsource/inter/files/inter-latin-700-normal.woff2" "$N/@fontsource/inter/files/inter-latin-800-normal.woff2" \
   "$N/@fontsource/instrument-serif/files/instrument-serif-latin-400-italic.woff2" fonts/
printf '{"id":"%s","name":"%s"}\n' "$NOM" "$NOM" > meta.json
printf '{"paths":{"blocks":"compositions","components":"compositions/components","assets":"assets"}}\n' > hyperframes.json

# Logo et photos de chantier nommées dans le modèle, prises sur le site.
if grep -q 'assets/logo.webp' index.html; then curl -fsS -o assets/logo.webp "$SITE/logo-unic-512.webp"; fi
for img in $(grep -oE '"(ref|realis|galerie|hero|avantapres|service|deco)-[a-z0-9-]+"' index.html | tr -d '"' | sort -u); do
  curl -fsS -o "assets/$img.webp" "$SITE/$img.webp"
done

export HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 HYPERFRAMES_NO_UPDATE_CHECK=1 HYPERFRAMES_SKIP_SKILLS=1 HYPERFRAMES_NO_AUTO_INSTALL=1
# Contrôle avant le rendu : UNIC_VIDEO_IMAGES="1.2,4.5,9" écrit ces images arrêtées dans le dossier de sortie, sans filmer.
if [ -n "${UNIC_VIDEO_IMAGES:-}" ]; then
  "$N/.bin/hyperframes" snapshot --at "$UNIC_VIDEO_IMAGES" --no-end --describe false -o "$SORTIE"
else
  "$N/.bin/hyperframes" render -q standard -f 30 -o "$SORTIE"
fi
echo "OK $SORTIE"
