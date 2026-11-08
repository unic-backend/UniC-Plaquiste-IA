# Plan A : Claude (Claude Code) · Plan B : UniC IA

Décision du patron (8/11/2026) : **Claude est le plan A, UniC IA le plan B.**

| | Plan A : Claude Code | Plan B : UniC IA |
|---|---|---|
| Quoi | Une session Claude Code sur ce dépôt, avec l'abonnement du patron | Le chat de l'appli (serveur Render, API Claude) |
| Coût | Compris dans l'abonnement, pour usage personnel | Payant à l'usage (crédit API) |
| Quand | Par défaut : devis, factures, prospection, appels d'offre, pub, site | Quand le patron a du crédit et veut l'appli : chat, mails, agenda, téléphone |
| Sans crédit | Marche | S'arrête. Reste sans IA : **Calcul par pièce**, prix, PDF, sauvegardes |

Le **serveur** reste la base de référence (clients, prix, documents). Les deux plans doivent y revenir : une seule base.

## Marche à suivre, plan A
1. **Récupérer les données** : boîte mail › dossier `UniC-Sauvegardes` › la sauvegarde la plus récente (`.zip`, ou `.zip.enc` avec mot de passe).
2. **Ouvrir Claude Code** sur ce dépôt et écrire : **« Plan A : suis docs/PLAN-A-ET-B.md »** en joignant la sauvegarde.
3. Claude **restaure** la sauvegarde dans une base locale (`backup.restore(données, mot_de_passe)`) et travaille avec le vrai code : calculs, prix, PDF, numérotation qui continue.
   Il prépare des **brouillons**. **Toi seul** envoies, publies ou paies.
   Il lit d'abord `docs/MEMOIRE-CLAUDE.md` (prix, règles, savoir d'UniC) ; un calcul de pièces se fait avec `python scripts/unic_calcul.py`.
4. **Ramener le travail au serveur** : `python scripts/planb_export.py` produit `dossier-claude-AAAA-MM-JJ.json` (devis, factures et clients créés depuis la sauvegarde).
   Dans l'appli : **Paramètres › Moteur & santé › Sauvegardes › « Importer un dossier de Claude… »**.
   - Rejouer le même fichier ne crée **aucun doublon**.
   - Même numéro, autre contenu : **conflit**, rien n'est écrasé, l'écran dit lesquels.
   - Un client déjà connu par son nom est réutilisé. Les PDF sont refaits par le serveur.
   - Hors import : versements, bons de commande et de livraison, mémoire, pièces jointes (dit à l'écran, pas oublié en silence).

## Règles
- Pas de clé API, de mot de passe ni de jeton dans la conversation. Pas de secret dans le dépôt.
- On ne restaure **jamais** une sauvegarde par-dessus le serveur sans accord du patron.
- Zones protégées (`AGENTS.md`) : Claude n'y touche pas. Branche + pull request, jamais `main`.
- Rien n'est envoyé, publié ni supprimé sans le clic du patron.
- Le serveur d'UniC n'utilise **jamais** l'abonnement : Anthropic l'interdit ([règles](https://code.claude.com/docs/en/legal-and-compliance.md)).

## Limites connues
- La sauvegarde date de la veille au plus : un prix changé depuis n'y est pas.
- Pendant une session plan A, le serveur peut créer ses propres documents : les numéros peuvent se croiser (même client, même jour). L'import le détecte (conflit) sans rien écraser.
- L'abonnement a ses propres limites d'usage.
- Pas de mail, agenda ni réseaux depuis Claude Code, sauf connexions ajoutées à la session.
- Appels d'offre : recherche Internet, accès aux portails officiels non vérifié.

Voir aussi : `docs/PLAN-B.md` (première version, remplacée par ce document).
