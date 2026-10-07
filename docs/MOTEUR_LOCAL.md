# Moteur local (PC NVIDIA A2000) — quand Claude ne répond pas

Le PC répond à la place de Claude, avec un modèle installé sur le PC. Rien à ouvrir sur la box : c'est le PC qui va chercher
les questions sur le serveur. PC éteint = l'IA répond seulement avec les réponses validées (bouton « Retenir »).

## Installation (une seule fois, PC allumé)
1. Installer **Ollama** pour Windows : https://ollama.com/download
2. Ouvrir « Invite de commandes » et taper : `ollama pull qwen2.5:7b` (≈ 4,7 Go, une fois)
3. Installer **UniC AI pour Windows** (GitHub → Actions → « Desktop apps » → artifact `unic-ai-windows`)
4. Ouvrir UniC AI sur le PC, se connecter (adresse du serveur + code d'accès)
5. Laisser l'appli ouverte (réduite) : Paramètres › Moteur & santé affiche « pc — ok »

## Ce qu'il fait / ne fait pas
- Répond aux questions avec la mémoire, la base UniC et la conversation ; dit « Je ne sais pas » sinon.
- Ne crée pas de devis, ne lit pas les mails, ne cherche pas sur Internet (pas d'outils).
- Les calculs de plaques et les documents restent faits par le moteur métier du serveur.
