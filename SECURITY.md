# Politique de sécurité — UniC AI

UniC AI est l'assistant de travail d'UniC Plaquiste (devis, factures, clients, documents). Il manipule des données d'entreprise : une faille doit être signalée **en privé**, jamais en public.

## Versions prises en charge

| Version | Support |
|---|---|
| `main` (déployée sur Render) | ✅ corrigée en priorité |
| Dernier APK Android publié depuis `main` | ✅ |
| Anciens APK, branches, forks | ❌ mettre à jour d'abord |

## Signaler une vulnérabilité

1. Onglet **Security** du dépôt › **Report a vulnerability** (signalement privé GitHub).
2. Si ce bouton n'est pas disponible, contacter directement le propriétaire du dépôt. **Ne pas** ouvrir d'issue, de pull request ni de discussion publique avec les détails.
3. Décrire : ce qui est touché (route, écran, fichier), les étapes pour reproduire, l'effet constaté, la version ou la date. Ne jamais joindre de vraies données de clients, de clés ni de mots de passe.

## Délais visés (objectifs, pas une garantie)

- Accusé de réception : sous 3 jours ouvrés.
- Première évaluation (réelle ou non, gravité) : sous 7 jours.
- Correctif des failles critiques (accès sans autorisation, lecture de fichiers, fuite de clés, exécution de code) : dès que possible, avant toute nouvelle fonction.
- Information de la personne qui a signalé, puis publication d'un avis une fois le correctif en ligne.

## Divulgation responsable

- Laisser un délai raisonnable pour corriger avant toute publication.
- Se limiter à ce qui prouve la faille : ne pas lire, copier, modifier ni supprimer de données qui ne vous appartiennent pas.
- Interdits : déni de service, hameçonnage ou ingénierie sociale visant le personnel ou les clients, tests sur des comptes ou données de tiers, accès physique.
- Les signalements de bonne foi respectant ces règles sont les bienvenus et seront traités avec considération.

## Ce qui est dans le périmètre

Serveur (API FastAPI), application web et Android, fichiers importés (PDF, images, documents), connecteurs (Gmail, GitHub, Instagram, LinkedIn, Higgsfield), agents automatiques, sauvegardes.
Hors périmètre : services tiers eux-mêmes (Render, GitHub, Anthropic…), qualité de la réponse d'une IA sans effet de sécurité.

## Protections déjà en place (résumé)

Accès par code ou compte (fermé par défaut en production), sessions révocables, limite des essais de connexion, fichiers importés contrôlés (taille, type réel, archives piégées), contenus de tiers traités comme des données (jamais des ordres), actions sensibles de l'IA refusées par le serveur sans demande du propriétaire, agents bornés (durée, appels, outils, arrêt d'urgence), secrets chiffrés et jamais dans le code, tests automatiques de sécurité à chaque pull request. Détail : `AGENTS.md`, `ARCHITECTURE.md`.
