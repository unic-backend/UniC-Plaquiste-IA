# Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| « Code d'accès requis » (401) | Mauvais code ou jeton expiré | Se reconnecter ; code = variable `UNIC_ACCESS_CODE` sur Render |
| « Trop d'essais » (429) | 10 échecs en 10 min depuis la même IP | Attendre 10 min |
| « Claude n'a pas pu répondre : crédit… » | Crédit Anthropic épuisé | Recharger sur console.anthropic.com |
| « clé API refusée » | `ANTHROPIC_API_KEY` absente/fausse | Corriger sur Render, redéployer |
| Fichier refusé (415) | Extension non autorisée ou contenu ≠ extension | Formats : pdf, docx, xlsx/xlsm, txt/csv/md, dxf/ifc/dwg, jpg/png/webp/gif |
| Calcul refusé « Vérifie les unités » | Surface > 10 000 m² | Vérifier m/mm ; confirmer ou découper |
| Navigateur bloque l'API (CORS) | Origine non listée | Ajouter l'origine dans `ALLOWED_ORIGINS` (virgules) |
| `/api/health/ready` renvoie 503 | Base (ou Redis si `REDIS_URL`) injoignable | Lire le champ `checks` ; vérifier le disque `/data` |
| Mails non lus | IMAP non branché | Connecter le compte dans l'appli (Courrier) |
| Erreur 500 « Erreur interne » | Bug serveur | Voir Atelier › Problèmes (le détail est journalisé côté serveur) |
| L'IA ne répond plus, calculs oui | `LLM_ENABLED=false` | Remettre `true` |

Tests : `make test`. Qualité : `make lint`. Santé : `GET /api/health/live` et `/api/health/ready`.
Si les tests échouent à cause d'une vieille base de test : supprimer le dossier pointé par `UNIC_DATA_DIR`.
