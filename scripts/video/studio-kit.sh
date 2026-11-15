#!/usr/bin/env bash
# Kit « Video Studio » (github.com/owlinthebarnai/video-studio-kit) : 50+ styles de vidéo pour TOUS les sujets
# (science, histoire, explications YouTube, « What if », typographie animée, vue éclatée 3D, pâte à modeler…), pas seulement UniC.
# Installé HORS du dépôt (~/.cache/video-studio-kit), à un commit figé, relu le 15/11/2026. Mode d'emploi d'un style :
# ~/.cache/video-studio-kit/.claude/skills/<style>/SKILL.md (Claude le lit avant d'écrire la vidéo).
# Usage : bash scripts/video/studio-kit.sh [--competences]   (--competences : relie aussi ces fichiers dans ~/.claude/skills,
#         seulement si le propriétaire l'a demandé : c'est la configuration de Claude)   puis rendu d'une « frame page » :
#   node ~/.cache/video-studio-kit/video-studio/tools/page-render.mjs <dossier> --out clip.mp4 [--size 1080x1920]
# Licences : voir THIRD_PARTY.md du kit. MIT pour la plupart ; sans licence : compétences remotion-*, claude-animation-styles,
# et le code propre au kit (sci-*, exploded-product, video-studio) → usage personnel, ne jamais le recopier dans ce dépôt.
set -euo pipefail
KIT="${VIDEO_STUDIO_KIT:-$HOME/.cache/video-studio-kit}"
COMMIT=fbd31eb4ca70e774e570a096843329a4c91349ce

if [ ! -d "$KIT/.git" ]; then
  mkdir -p "$KIT" && git -C "$KIT" init -q && git -C "$KIT" remote add origin https://github.com/owlinthebarnai/video-studio-kit.git
fi
if [ "$(git -C "$KIT" rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
  git -C "$KIT" fetch -q --depth 1 origin "$COMMIT" && git -C "$KIT" checkout -q FETCH_HEAD
fi

# Le moteur d'images du kit cherche Playwright et three.js dans repos/lemomo-ai_lemo-opuscar. Pas de téléchargement de
# navigateur : on prend le Playwright déjà installé (sessions Claude Code) et three@0.187.0 figé.
LEMO="$KIT/repos/lemomo-ai_lemo-opuscar"
mkdir -p "$LEMO/node_modules"
[ -f "$LEMO/package.json" ] || echo '{"private":true}' > "$LEMO/package.json"
PWC="$(dirname "$(dirname "$(node -e "console.log(require.resolve('playwright'))")")")/playwright-core"
[ -d "$PWC" ] || { echo "Playwright introuvable : installe-le ou lance « node setup.mjs » dans $KIT"; exit 1; }
[ -d "$LEMO/node_modules/three" ] || npm install --prefix "$LEMO" --no-save --no-audit --no-fund --silent three@0.187.0
ln -sfn "$PWC" "$LEMO/node_modules/playwright-core"   # après npm : npm efface les liens qu'il ne connaît pas

# Compétences : liens seulement avec --competences (jamais d'écrasement d'une compétence existante qui n'est pas un lien du kit).
n=0
[ "${1:-}" = "--competences" ] && mkdir -p "$HOME/.claude/skills"
for d in "$KIT/.claude/skills/"*/; do
  [ "${1:-}" = "--competences" ] || break
  name="$(basename "$d")"; dest="$HOME/.claude/skills/$name"
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then echo "garde la compétence existante : $name"; continue; fi
  ln -sfn "${d%/}" "$dest"; n=$((n + 1))
done
echo "OK kit vidéo : $KIT @ ${COMMIT:0:7} ; $(ls -d "$KIT/.claude/skills/"*/ | wc -l) modes d'emploi dans $KIT/.claude/skills ($n reliés)"
echo "Styles prêts ici : sci-flat, sci-fluoro, sci-molecular, sci-notebook, exploded-product (page-render), HyperFrames (scripts/video)."
echo "Autres styles (tvhead, Remotion, Blender, lemo…) : « node setup.mjs » dans $KIT (télécharge des navigateurs et modèles)."
