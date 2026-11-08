> **Remplacé par `docs/PLAN-A-ET-B.md`** (décision du patron : Claude = plan A, UniC IA = plan B ; l'import des dossiers vers le serveur existe maintenant). Ce texte garde la première version.

# Plan B : travailler quand UniC IA ne répond pas (plus de crédit API)

Plan A : UniC IA (le chat de l'appli) appelle l'API Claude, payante à l'usage. Quand le crédit est vide, le chat ne répond plus.
Plan B : on garde les mêmes règles, les mêmes prix, les mêmes PDF, **sans payer l'API**. Rien de ce qui calcule ou fabrique un document n'a besoin d'elle.

## Ce qui marche sans l'API (vérifié)

| Besoin | Où | Comment |
|---|---|---|
| Matériel d'une ou plusieurs pièces + prix + devis brouillon | Appli › Entreprise › **Calcul par pièce** | Aucun appel payant. « Créer le devis » donne un PDF au même format que le chat. |
| Calcul, plan de pose, traçage des décors, électricité et clim (calculs) | Moteur de code (`calc.py`, `plan_pose.py`, `plafond_design.py`, `elec.py`) | Même résultat que dans le chat : c'est du code, pas de l'IA. |
| Prix | Appli › Matériaux & prix | Tes prix servent aussi hors IA. |
| Sauvegarde de tes données | Chaque jour, copie dans ta boîte mail (dossier `UniC-Sauvegardes`) | Contient devis, factures, clients, mémoire, prix. |

## Plan B complet : Claude Code avec TON abonnement

Claude Code peut travailler avec ton abonnement Claude (sans API), **pour ton usage personnel**, avec le programme officiel. Anthropic interdit
de brancher un abonnement dans une appli ou un serveur : le serveur d'UniC ne l'utilise donc jamais. [Règles](https://code.claude.com/docs/en/legal-and-compliance.md).

Marche à suivre (à toi, sur ta session Claude Code) :
1. Télécharge la dernière sauvegarde : boîte mail › dossier `UniC-Sauvegardes` › le fichier le plus récent (`.zip`, ou `.zip.enc` si tu as mis un mot de passe).
2. Ouvre Claude Code sur ce dépôt et écris : **« Plan B : suis docs/PLAN-B.md »**, avec le fichier de sauvegarde.
3. Claude restaure ta sauvegarde dans une base **locale** (`backup.restore(données, mot_de_passe)`), puis travaille avec le vrai code :
   devis, factures, bons, calculs, PDF. La numérotation continue (testé : `UC-2026-1108-AD` puis `UC-2026-1109-AD`).
4. Il prépare des **brouillons**. **Toi seul** envoies, publies ou paies.
5. Même session : veille d'appels d'offre, listes de prospects, textes de pub, idées de site. Toujours des brouillons à valider.

## Règles du plan B
- Jamais de clé API, mot de passe ou jeton dans la conversation. Un mot de passe de sauvegarde se tape, il ne se colle pas dans un fichier du dépôt.
- On ne restaure **jamais** une sauvegarde par-dessus le serveur de production sans ton accord.
- Zones protégées (`AGENTS.md`) : Claude n'y touche pas. Branche + pull request, jamais `main`.
- Rien n'est envoyé, publié ni supprimé sans ton clic.

## Limites connues (honnêtes)
- **Deux bases** : un devis fait en plan B vit dans la base locale, pas sur le serveur. Il n'y a pas encore d'import vers le serveur.
  En attendant : envoie le PDF au client, note son numéro, et n'écrase pas le serveur. **À construire** si le plan B devient courant.
- La sauvegarde date de la veille au plus : un prix changé depuis n'y est pas.
- L'abonnement a ses propres limites d'usage (messages par période) : à consulter dans ton compte.
- Pas de mail, agenda ni réseaux depuis le plan B, sauf connexions que tu ajoutes à ta session Claude Code.
- Recherche d'appels d'offre : par recherche Internet, sans garantie d'accès aux portails officiels : à tester avant de compter dessus.
