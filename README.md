# UniC AI

Plateforme métier **exclusivement pour UniC Plaquiste**.

Ce n’est pas un assistant généraliste. C’est un employé digital pour la plaquisterie, les cloisons, les faux plafonds, le plâtre, la peinture, les portes, les finitions, le métré, le devis, la facture, le chantier.

**Qualité > quantité.** Chaque bouton fait quelque chose de réel. Ce qui n’est pas prêt est marqué **NON DISPONIBLE**.

---

## Principe

L’utilisateur écrit ce dont il a besoin, joint un plan ou une photo, et obtient un résultat professionnel **vérifiable**.

Exemple :

> Cloison 320 m × 2,50 m, deux faces. Fais le devis.

UniC AI calcule la surface (1 600 m²), les plaques, l’ossature, produit un **PDF réel**, et n’invente **aucun prix** UniC.

Statuts de donnée : `CONFIRMED` · `ESTIMATED` · `ASSUMED` · `MISSING`

---

## Architecture (le PC personnel n’est pas le serveur)

```
Téléphone / tablette / laptop
        │
     Internet
        ▼
  Cloud / VPS  ── UniC AI (cette application)
        │
        ├── base SQLite ou PostgreSQL
        └── fichiers (plans, PDF générés)

Optionnel : PC atelier = worker IA locale / GPU
Si le PC est ÉTEINT, l’application continue de fonctionner.
```

Déploiement recommandé : **Docker sur un VPS**.

```bash
cp .env.example .env
docker compose up -d --build
```

Données persistantes : volume `unic-data`.

---

## Lancer en développement

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
UNIC_DATA_DIR=../data uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend (autre terminal)
cd frontend
npm install
npm run build   # ou npm run dev (proxy /api → :8000)
```

En production locale, compiler le frontend puis servir uniquement uvicorn : l’API sert l’interface.

Application **solo** : aucune connexion. Écoute sur `127.0.0.1` seulement. Pour l’exposer sur Internet, protège-la (VPN, Tailscale ou proxy avec mot de passe).

---

## Ce qui fonctionne vraiment

- Authentification, rôles, sessions JWT
- Interface conversation (desktop + smartphone)
- Téléversement PDF / Office / images, photo chantier (appareil)
- Lecture PDF page par page, recherche (« trouve les portes »)
- Moteur BTP : surfaces, plaques, montants, rails, peinture, enduit — formules visibles
- Catalogue matériaux **sans prix inventés**
- Devis, factures, bons de commande, bons de livraison, rapports — **PDF réels téléchargeables**
- Approbation humaine (brouillon → approuvé)
- Clients, fournisseurs, chantiers, mémoire projet
- Saisie vocale navigateur (Chrome / Android)
- Tableau de santé, journal d’audit
- Sauvegarde / restauration (`scripts/backup.py`, `scripts/restore.py`)

## NON DISPONIBLE (volontairement, pas simulé)

| Capacité | Raison |
|---|---|
| OCR | Tesseract non installé |
| Vision / interprétation photo | Pas de clé IA vision |
| Envoi d’e-mail | SMTP non configuré |
| Publication réseaux | Connecteur absent |
| Google Business | API absente |
| Mise à jour site public | Connecteur absent |
| LLM conversationnel | `OPENAI_API_KEY` / `LOCAL_AI_URL` absents — le moteur métier fonctionne quand même |

Les brouillons d’e-mails et de posts peuvent être **rédigés**, jamais envoyés tout seuls.

---

## IA hybride

Abstraction `AIProvider` :

- `CloudAIProvider` — OpenAI-compatible (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`)
- `LocalAIProvider` — serveur atelier (`LOCAL_AI_URL`) si le PC est allumé
- `VisionAIProvider`
- `EmbeddingProvider`

Le cloud est prioritaire pour que le téléphone continue de marcher PC éteint.

---

## Tests

```bash
cd backend
. .venv/bin/activate
UNIC_DATA_DIR=/tmp/unic-test-data pytest -q
```

Couverture minimale : calcul 320×2,50×2 = 1 600 m², plaques, auth, PDF `%PDF`, prix jamais inventés.

---

## Sauvegardes

```bash
python scripts/backup.py
python scripts/restore.py data/backups/unic-backup-…
```

Une sauvegarde n’est considérée comme valide **qu’après une restauration testée** (ouverture d’un PDF de devis).

---

## Données

Tout reste sous contrôle d’UniC Plaquiste (SQLite fichier ou PostgreSQL via `DATABASE_URL`). Export = copie du volume `/data`.

UniC AI n’invente pas : prix, clients, fournisseurs, cotes, paiements, clauses.

---

## Licence interne

Usage exclusif UniC Plaquiste.
