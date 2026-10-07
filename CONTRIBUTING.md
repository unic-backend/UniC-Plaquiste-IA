# Contribuer

## Démarrer
```bash
cp .env.example .env
make dev      # serveur sur :8000
make test     # tests serveur
make lint     # ruff + bandit (comme la CI)
```
Interface : `cd frontend && npm install && npm run dev`.

## Branches et commits
- Branche par sujet, fusion par pull request. `main` reste déployable.
- Commits en Conventional Commits : `feat`, `fix`, `perf`, `chore`, `docs`, `refactor`.
- Petits commits, un sujet chacun.

## Avant d'ouvrir une PR
- [ ] `make test` et `make lint` passent (la CI rejoue backend, qualité, types et build frontend).
- [ ] Aucun secret dans le code : tout passe par `.env` (voir `.env.example`).
- [ ] Aucune donnée inventée : prix, TVA et taux viennent du propriétaire ou des réglages.
- [ ] Un test pour chaque comportement ajouté ; les calculs ont une valeur vérifiée à la main.
- [ ] Une option facultative = un réglage qui la coupe.
- [ ] Rien ne s'envoie, ne se publie ni ne se supprime sans clic du patron.

## Zones protégées
`repair.py`, `selfcare.py`, `trust.py`, l'authentification et le déploiement ne sont pas modifiables par l'auto-réparation : relecture humaine obligatoire.

## Outils et agents IA
Tout outil ou agent IA (Codex, Cursor, Copilot, Gemini, Claude Code…) suit **`AGENTS.md`** : il peut ajouter fonctionnalités, outils, agents et tests, mais ne sort pas de la base,
ne recrée rien de ce qui existe et ne touche pas aux zones protégées. Le job CI **guardrails** (`scripts/guardrails.py`) le vérifie sur chaque pull request ;
le propriétaire lève un blocage voulu avec l'étiquette `core-change-approved`.
