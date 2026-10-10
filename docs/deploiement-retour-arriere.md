# Retour arrière après un mauvais déploiement — proposition

**Statut : proposition, rien n'est actif.** Activer = copier un fichier dans `.github/workflows/` (zone protégée : PR + label `core-change-approved`, posé par le propriétaire).

## Ce qui existe déjà
- Render : `healthCheckPath: /api/ping`. Si la nouvelle version ne démarre pas, Render garde l'ancienne en ligne.
- `uptime.yml` : contrôle externe toutes les 30 min (santé + API fermée), issue « 🔴 Serveur en panne ».
- Base de données : colonnes ajoutées seulement (`ensure_columns`) → l'ancienne version fonctionne avec la nouvelle base. **Le retour arrière est donc sans danger pour les données.**

## Le trou
Une version qui démarre (ping OK) mais qui est cassée (base injoignable, API ouverte, erreurs) reste en ligne jusqu'au prochain contrôle (≤ 30 min), et personne ne revient en arrière.

## Ce que propose `docs/deploiement-retour-arriere-proposition.yml`
Après chaque fusion dans `main` :
1. Attend la fin du déploiement Render de CE commit (ou 10 min sans clé Render).
2. Contrôle : `/api/health/ready` = 200, `/api/materials` sans code = 401, `/api/ping` ok.
3. Si échec : issue « 🟠 Déploiement dégradé » (e-mail GitHub) avec la marche à suivre.
4. **Seulement si tu l'autorises** : retour arrière automatique vers la version précédente (API Render `POST /v1/services/{id}/rollback`).
5. Si sain : ferme l'alerte.

## Déclencheurs (corrigé après essai réel)
Les fusions automatiques de GitHub ne déclenchent pas les workflows « push » (constaté sur #43). Le contrôle tourne donc aussi **toutes les 15 min** (état actuel, sans attente, sans retour arrière automatique : il n'est pas lié à un déploiement précis), en plus de la fusion manuelle et du lancement à la main.

## Trois niveaux, à ton choix
| Niveau | À faire | Résultat |
|---|---|---|
| 1. Alerte seule | Copier le fichier. Rien d'autre. | Alerte dans les minutes, retour arrière à la main (2 clics Render). |
| 2. Attente exacte | + secret `RENDER_API_KEY` et variable `RENDER_SERVICE_ID` | Contrôle dès que Render a fini. |
| 3. Retour arrière auto | + variable `UNIC_AUTO_ROLLBACK` = `true` | Version précédente remise toute seule. |

Recommandation : **niveau 1 d'abord**, niveau 3 après quelques semaines sans fausse alerte.

## Limites (honnêtes)
- L'API Render de retour arrière vient de sources tierces et de la page [render.com/docs/rollbacks](https://render.com/docs/rollbacks) : non testée ici, à valider une fois au niveau 3.
- Après un retour arrière par l'API, le déploiement automatique reste actif : le prochain `main` redéploie (voulu : tu corriges, tu fusionnes).
- Le retour arrière ne répare pas une base corrompue : les sauvegardes vérifiées (Atelier) restent la protection.
- La clé Render ne se met JAMAIS dans le dépôt ni dans le chat : GitHub › Settings › Secrets › Actions.
