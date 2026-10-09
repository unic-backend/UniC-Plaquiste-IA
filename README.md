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

Application **mono-propriétaire**. Sur Internet, définis `UNIC_ACCESS_CODE` (et un mot de passe dans l'appli) : sans code, l'API est ouverte. Voir `ARCHITECTURE.md`, `CONTRIBUTING.md`, `TROUBLESHOOTING.md`.

---

## Ce qui fonctionne vraiment

- Connexion par e-mail + mot de passe (ou code d'accès), jetons de session révocables
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

## Courrier, réseaux, fiche Google

- **Courrier** : lecture IMAP (lecture seule), résumé, réponse proposée, **approbation puis envoi** SMTP. Rien ne part seul.
- **Réseaux & Google** : 11 cibles (LinkedIn, Facebook, Instagram, TikTok, YouTube, Reddit, X, WhatsApp, Pinterest, fiche Google, site). Brouillon → revue → approbation → publication **manuelle**. Publication auto = NON DISPONIBLE (API/OAuth non configurées).
- **Booster** : plan de conseils par IA. Aucune action lancée, aucun budget dépensé.
- IA requise pour résumer / rédiger : `OPENAI_API_KEY` ou `LOCAL_AI_URL`.

## Connecter la fiche Google

Prérequis : tu es propriétaire de la fiche. Google exige d'**approuver** l'accès à l'API Business Profile.

1. 🔑 console.cloud.google.com → nouveau projet → active **Business Profile API** (+ *My Business Business Information API*).
2. 📨 Demande l'accès API : formulaire « GBP API access request » (délai : jours). Sans accord, Google répond 403.
3. 🪪 *Identifiants* → ID client OAuth (type Application Web). Redirect : `https://developers.google.com/oauthplayground`.
4. 🎫 Va sur developers.google.com/oauthplayground → ⚙ « Use your own OAuth credentials » → colle ID + secret → scope `https://www.googleapis.com/auth/business.manage` → autorise → **Exchange** → copie le *refresh token*.
5. 🆔 `GBP_ACCOUNT_ID` et `GBP_LOCATION_ID` : les nombres dans `accounts/{ID}/locations/{ID}` (API *accounts.list* / *locations.list* dans le Playground).
6. ⚙️ Mets les 5 variables dans `.env`, relance. La page **Réseaux & Google → Fiche Google** passe à « Charger fiche et avis ».

Fonctions : audit de la fiche (lacunes réelles), liste des avis, réponses proposées par l'IA, actualités. **Tout passe par brouillon → revue → approbation → « Publier sur Google »**.

## Moteurs IA

- **Par défaut : modèle local** (`LOCAL_AI_URL`, ex. Ollama `http://IP:11434/v1`, + `LOCAL_AI_MODEL`). Serveur éteint → repli sur OpenAI-compatible si configuré, sinon message honnête.
- **Raisonnement profond : Claude** (`ANTHROPIC_API_KEY`). Jamais automatique : bouton ✦ dans le chat, ou « réfléchis en profondeur ». Facturé à l'usage.
- **Claude seul** (sans modèle local) : usage courant = `ANTHROPIC_FAST_MODEL` (Sonnet), ✦ = `ANTHROPIC_MODEL` (Opus). Chaque message IA est facturé.
- **Relais secondaire : Vibecode** (`VIBECODE_API_KEY`, clé `vk-…`, https://vibecode.moe — doc : https://vibecode.moe/setup/cc). Même protocole qu'Anthropic (mêmes modèles Claude), fournisseur distinct avec sa propre clé.
  - Priorité : **Anthropic officiel d'abord**. Vibecode n'est essayé que si Anthropic échoue (quota épuisé, clé refusée, réseau/panne) ou n'est pas configuré ; si Vibecode échoue aussi → secours local (PC / `LOCAL_AI_URL`). Jamais deux requêtes payantes simultanées pour une même tâche.
  - Pas de bascule aveugle : une erreur de requête (400/404/422) ou un refus ne déclenche pas Vibecode.
  - Modèles : `VIBECODE_SONNET_MODEL` (quotidien), `VIBECODE_OPUS_MODEL` (✦), `VIBECODE_HAIKU_MODEL` (voix). Le fournisseur et le modèle réellement utilisés sont enregistrés (compteur d'usage, tarif Vibecode).
  - Après un quota épuisé chez Anthropic, celui-ci est « refroidi » `AI_QUOTA_COOLDOWN_S` secondes (défaut 300) : les messages suivants partent directement sur Vibecode.
  - Vérifier les modèles avant activation : `cd backend && python ../scripts/check_vibecode.py` (liste gratuite ; `--probe --yes` pour une sonde payante).
- Claude absent ou en panne → réponse du moteur local, signalée dans le message.

## Numérotation des documents

- **Devis** : `UC-AAAA-BLOC-CLI` — CLI = initiales prénom + nom du client (Ousmane Diop → `OD`). Le BLOC à 4 chiffres part de la date du jour (4 oct. = `1004`) puis appartient au client : Pape Diop `1004`, Awa Fall `1005`, Fallou Ndiaye `1006`, même le même jour ; le lendemain on continue. Un client qui revient garde son bloc : `UC-2026-1004-PD2`.
- **Documents liés** : numéro du devis + code → `…-OD-BC` (bon de commande), `…-OD-BL` (livraison), `…-OD-F` (facture), `…-OD-AV` (avoir). Plusieurs du même type : `-BC2`.
- Client inconnu : `XXX` (jamais inventé). Le numéro d'un brouillon se corrige quand une fiche client est rattachée.

## Application Android (vraie app, pas une PWA)

Capacitor emballe l'interface dans une app Android native (`frontend/android`). Elle se connecte à ton serveur UniC.

1. **Serveur** : héberge le backend en **https** et définis `UNIC_ACCESS_CODE` (code d'accès unique).
2. **APK** : GitHub → *Actions* → « Android APK » → dernier run → artefact `unic-ai-apk`.
3. **Installer** : télécharge l'APK sur le téléphone, ouvre-le, autorise « sources inconnues » une fois.
4. **Premier lancement** : saisis l'adresse du serveur (`https://…`) et le code d'accès.
5. Mises à jour : même clé de signature, la nouvelle version s'installe par-dessus.

Local : `cd frontend && npm run android:debug` (JDK 21 + Android SDK 35). La clé de signature du dépôt est une clé de **debug** : créer une vraie clé de release avant le Play Store.

## Hébergement (Render + domaine Netlify)

Netlify héberge des sites statiques : il ne peut pas faire tourner ce backend Python. Le domaine `unicplaquiste.com` reste sur Netlify ; on y ajoute **un sous-domaine** `ia.unicplaquiste.com` qui pointe vers Render. Les sites `www`, `app`, `expert` ne sont pas touchés.

1. render.com → *New* → *Blueprint* → dépôt `UniC-Plaquiste-IA` (branche à déployer) → `render.yaml`.
2. Saisir `UNIC_ACCESS_CODE` (code long) et `ANTHROPIC_API_KEY`.
3. Render → service → *Settings* → *Custom Domains* → `ia.unicplaquiste.com` → noter la cible CNAME.
4. Netlify → *Domains* → `unicplaquiste.com` → *DNS records* → ajouter `CNAME  ia  →  <cible Render>`.
5. App Android : adresse du serveur `https://ia.unicplaquiste.com` + le code.

## Recherche sur Internet

Avec Claude comme moteur, JARVIS cherche sur Internet quand la question dépend de l'actualité ou de faits récents, et cite ses sources (liens sous la réponse).
- À activer côté Anthropic : console.anthropic.com → **Settings** → **Privacy** (ou *Organization*) → autoriser **Web search**. Sans cela, l'IA répond sans recherche (sans erreur).
- Facturée à l'usage par Anthropic (en plus des jetons). Limite : `WEB_SEARCH_MAX_USES` recherches par réponse. Désactiver : `WEB_SEARCH_ENABLED=false`.
- Ne sert jamais pour les données privées de l'entreprise (prix, clients) : celles-ci viennent de la base UniC et de la mémoire.
