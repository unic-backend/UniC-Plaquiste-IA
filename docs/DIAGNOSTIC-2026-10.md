# Diagnostic UniC AI — octobre 2026

Revue technique, sécurité, qualité et feuille de route.
Périmètre : tout le dépôt à `main` (commit `3bca38c`, après la PR #44).

---

## 0. Vérification indépendante (revue après coup)

Ce diagnostic a été relu et **rejoué** avant d'être repris dans `main`. Rien n'a été pris sur parole.

**Confirmé en exécutant le code (avant / après) :**

| Point | Avant (`main`) | Après (cette branche) |
|---|---|---|
| Chute négative dans les réglages | `PUT /api/settings` accepté, puis **tout calcul plante** (`ValueError` non gérée) | `PUT` refusé (422), le calcul reste sain ; le renvoi complet des réglages par la page passe (200) |
| CORS en production (`UNIC_ENV=production`, sans `ALLOWED_ORIGINS`) | origine `https://evil.example` **autorisée** (préflight 200) | refusée (400) ; `https://localhost` (APK) et `unic://app` (PC) **toujours autorisées** ; bulle de discussion du site toujours joignable (204 / `*`, sans identifiants) |
| `/api/calc` saisie impossible | 500 | 400 avec la raison du moteur |

Suite complète sur l'état fusionné : **460 tests passent** (448 + les 12 de `test_input_bounds.py`), `ruff`, `bandit` et garde-fous OK, aucune zone protégée touchée.

**Corrections apportées au texte d'origine :**

1. **Gravité du CORS : « Élevée » → « Moyenne » (défense en profondeur).** Le défaut est réel (reproduit ci-dessus), mais un site tiers ne peut pas lire de données sans le code d'accès, qui voyage dans un en-tête qu'il ne connaît pas ; l'application n'utilise aucun cookie. Le correctif reste utile, il ne s'agissait pas d'une porte ouverte sur les données.
2. **Chiffres** : 460 tests (et non 451) sur l'état fusionné ; la « couverture de 85 % » n'a pas été revérifiée ici.
3. **Recommandations non retenues pour l'instant** (trop lourdes pour un usage mono-propriétaire, ou contraires au principe « fiabilité d'abord, pas plus d'agents ») : exposition Prometheus `/api/metrics` + table `HealthSample` (§6.1), liste d'« agents à ajouter » (§8), double moteur Claude/Vibecode (§6.3). Les autres pistes (CSP en mode rapport, `UNIC_SECRET_KEY`, durée de session, journal des lectures, limite du corps JSON, Dependabot, séparation des dépendances de test) restent valables ; ce sont des zones protégées ou des choix du propriétaire.

Le reste du document est conservé tel qu'écrit.

---

## 1. Verdict en une page

**Le projet est de bon niveau — nettement au-dessus de la moyenne des applications de cette taille.**
Ce n'est pas un prototype : 22 000 lignes de Python, 7 700 lignes de TypeScript, 51 tables, 220 routes,
54 outils d'IA, 451 tests serveur, 105 vérifications frontend, une couverture de code de 85 %, une CI à six
contrôles (garde-fous, qualité, tests, frontend, Android, contrôle après déploiement).

Ce qui distingue vraiment ce projet : **il refuse d'inventer**. Prix jamais devinés, statuts honnêtes
(`confirmed` / `estimated` / `assumed` / `missing`), une IA qui n'envoie, ne publie et ne supprime jamais sans
clic, des contenus de tiers traités comme des données et non comme des ordres, un moteur de calcul pur et testé
à la main. C'est rare, et c'est exactement ce qu'il faut pour un outil de devis.

**Mais trois failles concrètes ont été trouvées et reproduites**, dont une qui **cassait toute la calculatrice
depuis l'écran de réglages** (chaque devis répondait « Erreur interne du serveur »), et une **configuration CORS
qui ouvrait l'API à n'importe quel site web**. Les deux sont corrigées dans cette branche, avec tests.

### Chiffres mesurés

| Mesure | Valeur | Commentaire |
|---|---|---|
| Lignes serveur / interface | 21 954 / 7 712 | `backend/app` + `frontend/src` |
| Modules serveur | 77 | couches bien séparées (voir `ARCHITECTURE.md`) |
| Routes HTTP | 220 | 141 dans `api.py`, 59 réseaux, le reste terrain/voix/site (+ santé et site public dans `main.py`) |
| Outils IA exposés | 54 | dont 19 « sûrs » (lecture + brouillon) pour les agents |
| Tests serveur | 451 ✅ / 2 ⚠️ / 1 ⏭️ | les 2 échecs sont des paquets système absents de ma machine, pas du code |
| Couverture serveur | **85 %** | `orchestrator.py` 68 %, `pdfworker.py` 0 % : les deux plus faibles |
| Tests frontend | 105 ✅ | `tsc --noEmit` et `vite build` passent |
| Alerte d'analyse statique | Ruff ✅ · Bandit ✅ (aucune alerte moyenne/haute) | le socle est propre |
| Failles de dépendances | 1 (serveur) + 4 (interface) | voir §4.1 |

### Ce que j'ai corrigé et vérifié en direct

| # | Défaut | Gravité | État |
|---|---|---|---|
| 1 | `PUT /api/settings` acceptait une chute négative → **500 sur tout calcul et tout devis** | 🔴 Critique | ✅ corrigé + test |
| 2 | CORS : `*` avec identifiants **même en production** → toute origine web reflétée | 🟠 Moyenne (voir §0) | ✅ corrigé + test |
| 3 | `/api/calc` renvoyait **500** au lieu de 400 sur saisie impossible | 🟠 Moyenne | ✅ corrigé + test |
| 4 | Prix de vente **négatif ou nul** accepté (contredit « aucun prix inventé ») | 🟠 Moyenne | ✅ corrigé + test |
| 5 | Fiches client / fournisseur / matériau / projet **sans nom** acceptées | 🟡 Faible | ✅ corrigé + test |
| 6 | L'exception « accès local » ouvrait l'API derrière un proxy installé sur la même machine | 🟠 Moyenne | ✅ corrigé + test |

Détail, preuves et reproductions : §5. Tests ajoutés : `backend/tests/test_input_bounds.py` (12 tests).

---

## 2. Méthode

Tout ce qui suit a été **exécuté**, pas supposé :

1. Installation complète serveur + interface, puis `pytest` (451 tests), `tsc --noEmit`, `vite build`, `npm run test:phone`.
2. Analyse statique : `ruff` (F, E9 comme la CI, puis jeu élargi), `bandit`, `pip-audit`, `npm audit`.
3. Mesure de couverture réelle (`pytest-cov`) pour trouver les zones non testées.
4. **Serveur lancé en conditions de production** (`UNIC_ENV=production`, code d'accès défini) et sondé :
   accès sans code, traversée de chemin, en-têtes de sécurité, CORS par origine, préflight, limite d'essais de connexion,
   220 routes et une trentaine de saisies hostiles (négatifs, `NaN`, `infini`, 10¹², chaînes vides, 100 000 caractères).
5. Lecture du code des zones sensibles : `auth`, `security`, `trust`, `secrets_box`, `ratelimit`, `documents`,
   `repair` (auto-réparation), `agents` (agents automatiques), `selfcare` (surveillance), `fileedit`, `sitechat`.
6. Recherche de motifs à risque : injection SQL par f-string, `eval` / `exec` / `pickle`, `subprocess`, SSRF,
   URL configurable, `except Exception: pass`, XSS dans l'interface.

---

## 3. Ce qui est solide (à ne pas casser)

- **Authentification.** scrypt salé, jeton opaque dont seul le SHA-256 est en base (révocation immédiate),
  session glissante, liste des appareils, changement de mot de passe qui révoque les autres appareils.
  Limite d'essais à deux étages (8 par IP, 30 au total) — **testée en direct : 8 essais puis 429**.
- **Fermé par défaut.** Sans `UNIC_ACCESS_CODE` en production, l'API refuse : la protection existe (PR #15).
  Les en-têtes `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`
  et `Strict-Transport-Security` sont posés sur chaque réponse.
- **Traversée de chemin.** Les quatre variantes testées (`/../../etc/passwd`, `%2e%2e%2f`, `..%2f`,
  `/api/../.env`) renvoient 404. Le chemin est résolu puis comparé au dossier autorisé — la correction de la PR #26 tient.
- **Injection de prompt.** `trust.py` emballe tout contenu de tiers (e-mail, avis, fichier) comme donnée,
  détecte les formulations de manipulation et repère les secrets. Une suite de tests d'attaque existe (`test_injection.py`).
- **Injection SQL.** Aucune requête construite avec une valeur utilisateur ; les rares f-strings SQL n'emploient
  que des noms de table issus du schéma, et le commentaire `nosec B608` est justifié.
- **Chemins d'exécution.** Aucun `eval`, `exec`, `pickle`, `shell=True`. Les deux `subprocess` passent des listes
  d'arguments (pas de shell) avec délai maximal.
- **Moteur de calcul.** Fonctions pures, sans base ni IA. `check_inputs` refuse zéro, négatif, `NaN`, `infini`
  et les surfaces démesurées avec un message clair. Vérifié : 320 m × 2,50 m × 2 faces = 1 600 m² exact.
- **Auto-surveillance.** Incidents regroupés par empreinte et **persistés en base**, pouls des fils de fond,
  contrôle quotidien, surveillance de cohérence des documents (`integrity.py`), tableau de qualité qui dit
  « non mesuré » au lieu d'inventer un chiffre.
- **Auto-réparation prudente.** `repair.py` n'écrit jamais en production : branche à part, liste blanche de
  chemins, zones protégées refusées, PR soumise aux contrôles, fusion au clic du patron, jeton chiffré.
- **Interface.** Aucun XSS trouvé : le convertisseur Markdown échappe `&`, `<`, `>` **avant** d'ajouter ses
  propres balises. Aucun secret dans `localStorage` hors l'adresse du serveur et le code d'accès (choix assumé).
- **Sauvegardes.** Quotidiennes, vérifiées (`PRAGMA integrity_check`, `foreign_key_check`, nombre de lignes par table),
  restauration testable — la règle « une sauvegarde ne vaut qu'après restauration testée » est appliquée pour de vrai.

---

## 4. Sécurité

### 4.1 Dépendances (à traiter par le propriétaire — fichiers protégés)

| Paquet | Problème | Correctif | Risque réel |
|---|---|---|---|
| `pytest 8.3.4` (serveur) | `PYSEC-2026-1845` | 9.0.3 | Faible en production (outil de test), mais il est **dans `requirements.txt`**, donc installé sur le serveur |
| `vite ≤ 6.4.2` + `esbuild` | 4 avis (dont 1 élevé) | vite 8.x | Développement seulement — jamais servi en production |
| `react-router-dom 6.28` | 2 avis modérés (redirection ouverte, injection SSR) | 7.18.4 | **Faible ici** : pas de SSR, navigation par onglets, pas d'URL fournie par un tiers |

`backend/requirements.txt` et `.github/` sont des **zones protégées** : je ne les modifie pas.
Actions recommandées au propriétaire :

1. Passer `pytest` à `9.x` **ou** sortir les outils de test du fichier de production
   (`requirements-dev.txt`) — la seconde option est plus propre.
2. Ouvrir `frontend/package.json` : monter `vite` et `react-router-dom` (changement majeur, à faire sur une branche
   dédiée avec `npm run test:phone` et un test manuel de navigation).
3. Ajouter **Dependabot** (`.github/dependabot.yml`) : il n'existe pas, alors que six contrôles automatiques tournent déjà.

### 4.2 Ce qui manque côté durcissement

| Sujet | Constat | Recommandation |
|---|---|---|
| **En-tête CSP** | Aucune `Content-Security-Policy` (les autres en-têtes sont là) | `index.html` ne contient aucun script en ligne (tout passe par le module compilé) : `script-src 'self'` est jouable. L'interface pose en revanche des styles à l'exécution (thème, animations de révélation) : commencer en `Content-Security-Policy-Report-Only` pour mesurer les refus, puis réduire `style-src` |
| **Protection des branches** | `CODEOWNERS` et `AGENTS.md` sont écrits, mais la protection de `main` est **manuelle** et n'est peut-être pas activée | GitHub › Settings › Branches › `main` : exiger la relecture du propriétaire + les contrôles. **Sans ce réglage, rien ne bloque une fusion** (le dit `AGENTS.md` lui-même) |
| **Clé des secrets** | Sans `UNIC_SECRET_KEY`, la clé Fernet vit sur le même disque que la base | Définir `UNIC_SECRET_KEY` dans Render (une valeur, cinq minutes) |
| **Alerte d'incident** | Les incidents sont en base et visibles dans l'Atelier, mais **aucun canal ne prévient** (e-mail, SMS, notification) | Un incident critique découvert trois jours plus tard, c'est une panne silencieuse : voir §6.1 |
| **Durée de session** | 365 jours glissants | Ramener à 90 jours avec prolongation à l'usage, ou demander la reconnexion après 30 jours d'inactivité |
| **Journal des accès** | `AuditLog` couvre les écritures, pas les lectures | Ajouter la trace des lectures sensibles (export de base, téléchargement de sauvegarde) |
| **Limite de corps** | `read_upload` borne les fichiers, mais pas le corps JSON brut | Poser une limite globale (`MAX_BODY_MB`) sur les routes JSON |

### 4.3 Deux points de conception à connaître (pas des bugs)

- **Le code d'accès voyage dans un en-tête** puis dans `localStorage`. C'est cohérent avec un usage mono-propriétaire,
  et un défaut XSS le révélerait — mais aucun XSS n'a été trouvé et la liste d'origines est désormais stricte.
- **Pas de suppression physique** (décision assumée du propriétaire). Conséquence à garder en tête : les données
  « supprimées » restent en base ; une future demande RGPD/client devra prévoir un effacement réel.

---

## 5. Bugs et erreurs : ce qui a été trouvé, reproduit, corrigé

### 5.1 🔴 Critique — une chute négative cassait **tous** les calculs et **tous** les devis

**Reproduction** (avant correction) :

```bash
PUT /api/settings  {"default_waste": -0.5}      → 200 OK   (accepté et enregistré)
POST /api/calc     {"kind":"partition","length_m":10,"height_m":2.5}
                                                → 500 {"detail":"Erreur interne du serveur."}
POST /api/calc     {"text":"cloison 10 m x 2,50 m"} → 500
```

Journal serveur :

```
app/calc.py", line 182, in check_inputs
    raise ValueError(f"Le taux de chute doit être entre 0 % et 50 % (reçu : -50 %).")
```

**Cause.** `SettingsIn` (`api.py`) n'avait **aucune borne** sur `default_waste`, `board_width_m`, `board_height_m`,
`stud_spacing_m`, `vat_rate`, `default_margin`, `quote_validity_days` — seul `invoice_due_days` était borné,
et `put_settings` appliquait tout sans contrôle. Le moteur, lui, refuse correctement une chute négative :
la couche d'entrée et le moteur n'étaient pas d'accord.

**Portée.** Une valeur erronée saisie **une fois** dans l'écran Paramètres rendait l'application inutilisable
pour son usage principal (métré, devis, factures), sans message compréhensible. Aggravant : la plaque
« 0 m » était silencieusement remplacée par la valeur par défaut (1,20 m à la place de la demande).

**Correction.** Bornes alignées sur le domaine métier (chute 0–50 %, densité de plaque, entraxe, TVA 0–100 %,
marge 0–100 %, jours de validité), avec le commentaire expliquant le risque. Vérifié :

```
PUT /api/settings {"default_waste": -0.5}  → 422 (nomme « default_waste »)
POST /api/calc    {…}                      → 200 (le moteur fonctionne toujours)
```

### 5.2 🟠 Moyenne (voir §0) — CORS : n'importe quel site web pouvait appeler l'API

**Reproduction** (avant correction, en `UNIC_ENV=production`, sans `ALLOWED_ORIGINS`) :

```bash
curl -D- http://…/api/health/live -H "Origin: https://evil-site.example"
# access-control-allow-origin: https://evil-site.example
# access-control-allow-credentials: true
```

**Cause.** `_origins()` renvoie `[]` en production — puis le middleware était construit avec
`allow_origins=_origins() or ["*"]`. Le repli `"*"` annulait la protection voulue. Et comme Starlette avec
`allow_credentials=True` **renvoie l'origine de l'appelant** au lieu de `*`, la réponse devenait valide pour
n'importe quel site, en contradiction avec la ligne écrite dans `.env.example`
(« Vide en production = aucune origine externe »).

**Correction.** (a) plus de repli `"*"` en production ; (b) `allow_credentials=False` — l'application n'utilise
**aucun cookie** (la connexion passe par l'en-tête `X-Access-Code`), l'autorisation ne servait donc à rien et
rendait le navigateur permissif ; (c) liste blanche explicite des applications installées
(`https://localhost` pour le téléphone Capacitor, `unic://app` pour le PC Electron) — **sans cela, l'APK et
l'application PC auraient perdu l'accès au serveur**, régression que j'ai vérifiée et évitée ;
(d) CORS dédié pour la bulle de discussion du site public, appelée depuis un autre domaine (Netlify), qui reste
joignable de partout mais **sans identifiants** et uniquement sur les routes publiques.

Vérifié après correction :

| Origine | Requête simple | Préflight |
|---|---|---|
| `https://localhost` (APK) | ✅ autorisée | 200 |
| `capacitor://localhost` | ✅ autorisée | 200 |
| `unic://app` (PC) | ✅ autorisée | 200 |
| `https://evil-site.example` | ⛔ aucune en-tête | 400 |
| `https://unicplaquiste.com` sur `/api/public/chat` | ✅ autorisée (route publique) | 204 |

### 5.3 🟠 Moyenne — 500 au lieu de 400 : le message utile était perdu

`POST /api/calc` avec une longueur négative, nulle ou de 10³⁰⁰ renvoyait `500 Erreur interne du serveur`.
Le moteur produit pourtant un message parfait (« « longueur » doit être un nombre strictement positif (reçu : -5) ») :
la route ne l'attrapait pas, et `body.length_m and body.height_m` traitait `0` comme « non fourni ».
Aggravant : ces 500 alimentaient le compteur d'erreurs de la surveillance (`integrity.py`), et une faute de
frappe de l'utilisateur pouvait déclencher une fausse alerte de dégradation.

**Correction.** `ValueError` → 400 avec le message du moteur ; test `is not None` au lieu du test de vérité ;
calcul de surface ajouté (`kind=surface`), qui existait dans le moteur mais n'était pas exposé.

```
POST /api/calc {"kind":"partition","length_m":-5,"height_m":2.5}
→ 400 {"detail":"« longueur » doit être un nombre strictement positif (reçu : -5.0)."}
```

### 5.4 🟠 Moyenne — prix négatif ou nul accepté

`POST /api/materials/{id}/prices` acceptait `-5000`, `0` et `1e15`. La saisie **en série**
(`/api/materials/prices/bulk`) refuse déjà exactement ces valeurs — les deux routes qui font la même chose
n'appliquaient pas la même règle. Pour une application qui promet « aucun prix inventé », un prix négatif
accepté est une contradiction directe : une faute de frappe devient une ligne de devis.

**Correction.** Même règle que la saisie en série (`> 0`, ≤ 10⁹) sur la route unitaire.

### 5.5 🟡 Faible — fiches sans nom

`POST /api/customers` avec `{"name": ""}` créait un client vide ; 100 000 caractères étaient acceptés
(création renvoyée `200`). Idem pour fournisseurs, matériaux (SKU / nom / catégorie / unité vides) et projets.
Conséquence en cascade : listes illisibles, et le numéro de devis qui finit par `XXX` (prévu pour
« client inconnu », pas pour « client vide »).

**Correction.** Type `RequiredText` (espaces retirés, jamais vide, 200 caractères max) appliqué aux noms,
et bornes sur les textes libres. `"  Awa Fall  "` est désormais enregistré `"Awa Fall"`.

### 5.6 🟠 Moyenne — l'exception « même machine » ouvrait l'API derrière un proxy

**Reproduction** (avant correction) : serveur en production, **sans** `UNIC_ACCESS_CODE`, appel depuis la machine —
`GET /api/customers` → **200** (données accessibles) au lieu du 503 attendu.

**Cause.** `_is_loopback()` se fiait à `request.client.host`. Or un relais installé **sur la même machine**
(nginx, Caddy, routeur d'un hébergeur) fait arriver **toutes** les requêtes d'Internet depuis `127.0.0.1` :
la garde « fermé par défaut » de la PR #15 ne s'appliquait alors plus du tout.

**Correction.** La requête n'est considérée locale que si elle arrive **en direct** : la présence d'un en-tête de
transfert (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `X-Forwarded-Host`) suffit à la traiter comme distante.
L'usage local au poste de travail reste possible, la faille non.

### 5.7 Points mineurs relevés (non corrigés, sans urgence)

| Sujet | Constat |
|---|---|
| `x or défaut` | Plusieurs endroits traitent `0` comme « non renseigné » (`company.get("board_width_m") or 1.2`). Les bornes ajoutées suppriment le cas gênant, mais le motif reste à surveiller |
| Test dépendant du système | 2 tests échouent si `tesseract` / `libcairo2` sont absents (ils passent en CI et dans l'image Docker). Recommandation : `pytest.mark.skipif` avec la raison, pour que la suite soit verte partout |
| Avertissement SQLAlchemy | `revise.py:216` : `DELETE … expected to delete 4 row(s); 0 were matched`. Bénin, mais il masquerait un vrai problème le jour où il compte |
| Pauses bloquantes | `time.sleep(0.4)` dans `auth.login` : correct, mais consomme un fil du pool. La limite d'essais suffit déjà |
| Crochets de démarrage | `main.py` avale les exceptions de six initialisations (`except Exception: pass`). Un échec silencieux au démarrage n'apparaît nulle part — à journaliser en `warning` |
| Cohérence de nommage | Les routes mélangent `/api/calc` et `/api/calculate`, `/api/quotes` et `/api/export/quote.csv`. Cosmétique, mais à documenter |

---

## 6. Qualité, raisonnement, reconnaissance, surveillance

### 6.1 Surveillance — solide sur le fond, aveugle sur l'alerte

**Déjà là.** Incidents persistés et regroupés par empreinte ; pouls des fils de fond (sauvegarde, agents,
surveillance) avec relance automatique ; contrôle quotidien (base, disque, mémoire, Claude, sauvegardes) ;
surveillance de cohérence des documents (total ≠ somme des lignes, TVA incohérente, PDF manquant, montants
négatifs, numéros dupliqués) ; tableau de qualité qui refuse d'inventer ; workflow externe toutes les 15 minutes
et contrôle après déploiement avec retour arrière proposé.

**Les trois trous, par ordre d'importance :**

1. **Aucun canal d'alerte.** Un incident critique n'est visible qu'en ouvrant l'application. Si le disque est
   plein un samedi, personne ne le sait avant lundi. → un envoi d'e-mail (le connecteur SMTP existe déjà)
   sur incident critique et sur échec de sauvegarde, au maximum une fois par incident.
2. **Mesures en mémoire.** Le taux d'erreurs et les temps de réponse vivent dans une file en mémoire
   (`integrity._REQUESTS`) : perdus au redémarrage, invisibles de l'extérieur. → persister un point de mesure
   toutes les 5 minutes (table `HealthSample`) et exposer `/api/metrics` au format Prometheus, ce que Render
   peut surveiller directement.
3. **Pas de transaction synthétique.** Le contrôle après déploiement vérifie la santé, pas le **parcours
   réel**. → un test de bout en bout en lecture seule (connexion, lecture clients, calcul témoin) toutes
   les 15 minutes, avec alerte si le résultat change.

### 6.2 Précision — la bonne méthode, à étendre

**Déjà là, et c'est la bonne approche :** banc d'essai déterministe (`evals.py`) avec cas de référence et
interdictions (« ne jamais inventer les faces, la taille d'une porte, une longueur à partir d'une surface, un prix »),
notation par code et non par modèle ; statuts de donnée explicites ; provenance et « pourquoi ce montant ? » ;
contrôle indépendant des prix (`pricecheck.py`) et des totaux (`integrity.py`) ; contrôle des marges ;
vérification géométrique des plans.

**Où progresser :**

| Manque | Proposition |
|---|---|
| Le banc d'essai ne mesure que l'**extraction des dimensions** | Ajouter des cas « dossier complet » : demande floue → question, plan ambigu → `conflicting`, prix manquant → refus de chiffrer. Et **compter les résultats** dans le tableau Qualité au fil du temps |
| La précision n'est jamais comparée au **réel** | Journaliser l'écart entre le métré estimé et le métré exécuté (le pointage terrain existe déjà) : c'est la seule vraie mesure de justesse |
| Pas de **double vérification** sur un devis produit par l'IA | Rejouer les dimensions extraites dans le moteur pur et comparer aux lignes du devis avant approbation — le calcul est déjà là, il manque le branchement |
| `orchestrator.py` à 68 % et `pdfworker.py` à 0 % | C'est le cerveau et le générateur de PDF : priorité de test la plus rentable du dépôt |

### 6.3 Raisonnement

Table ronde (4 avis + arbitre), raisonnement profond ✦ (Opus), bascule maîtrisée Anthropic → Vibecode → local
avec refroidissement post-quota, recherche Internet citée, mémoire client/chantier, leçons apprises, révision
de devis (`revise.py`). C'est déjà au-dessus de ce que font la plupart des produits.

**Ce qui manque :** un **désaccord explicite**. Aujourd'hui la table ronde signale les divergences, mais
l'application ne dit jamais « deux moteurs ont répondu des choses différentes, je ne sais pas ». Un contrôle
croisé Claude / Vibecode sur les seules décisions à enjeu (devis > seuil) fermerait la boucle.

### 6.4 Reconnaissance

**Déjà là.** Texte natif des PDF, OCR Tesseract (fra + eng) avec rendu borné (300 DPI max, mémoire maîtrisée),
vision Claude (plans et photos, 1 568 px, 6 pages max), DXF et IFC (AutoCAD, Revit, ArchiCAD), lecture page
par page avec recherche, classification des pages, disponibilité **honnête** (« NON DISPONIBLE » si le moteur
manque plutôt qu'un faux résultat).

**Les manques :**

| Manque | Proposition |
|---|---|
| La vision dépend de Claude : sans clé, un plan scanné n'est qu'une image | Un repli local de reconnaissance (RapidOCR/ONNX) pour la lecture de cotes, en plus de Tesseract |
| Les **symboles** de plan (portes, fenêtres, gaines) ne sont pas reconnus | Explorateur déterministe des blocs DXF (`INSERT`) et des calques : les portes et fenêtres y sont déjà, sans IA |
| Aucune **confiance** attachée à une lecture | Un score par cote lue (« lisible », « à confirmer ») et l'interdiction de chiffrer sur une cote douteuse |
| L'échelle du plan n'est pas extraite | Lire le cartouche (échelle 1/50, 1/100) pour convertir les mesures papier — le levier de précision le plus fort sur les plans scannés |

---

## 7. Transformations à faire (plan priorisé)

### P0 — cette semaine (sécurité et disponibilité)

1. **Protection de `main` activée** sur GitHub (relecture du propriétaire + contrôles obligatoires). Sans elle,
   `AGENTS.md` et `CODEOWNERS` ne bloquent rien — c'est écrit dans le dépôt lui-même.
2. **Dépendances** : `pytest` (serveur) hors du fichier de production, puis `vite` / `react-router-dom`
   sur une branche dédiée. Ajouter **Dependabot**.
3. **`UNIC_SECRET_KEY`** défini dans Render (protège les secrets enregistrés, y compris en cas de fuite de la base seule).
4. **Canal d'alerte** sur incident critique et échec de sauvegarde (SMTP déjà branché).
5. **En-tête CSP** ajouté.

### P1 — ce mois (qualité et preuve)

6. **Mesures persistées** (`HealthSample`) + `/api/metrics`, pour voir une tendance au lieu d'un instantané.
7. **Tests manquants** sur `orchestrator.py` et `pdfworker.py` (les deux plus faibles du dépôt).
8. **Double vérification** des devis produits par l'IA dans le moteur pur avant approbation.
9. **Banc d'essai étendu** (dossiers complets) et suivi de son score dans le tableau Qualité.
10. **Suite de tests indépendante de la machine** (`skipif` explicites) pour que la CI soit verte partout.

### P2 — le trimestre (métier et autonomie)

11. **Fidélité du métré** : comparer métré estimé et métré exécuté (pointage déjà présent) → indicateur par chantier.
12. **Reconnaissance des symboles de plans** et lecture du cartouche (échelle) — gains de précision importants.
13. **Agents autonomes utiles** (section 8), deux ou trois à la fois, chacun avec son journal et son plafond.
14. **Postgres** si et seulement si plusieurs utilisateurs arrivent (décision documentée dans `ARCHITECTURE.md`).

### P3 — plus tard

15. Facturation conforme multi-pays (mentions légales, NINEA, TVA par région), multi-devises.
16. Export comptable, rapprochement bancaire léger.
17. Mode hors-ligne complet (la file d'attente existe déjà dans `offline.ts`, à étendre aux documents).

---

## 8. Agents à ajouter

Le socle est déjà excellent : `CustomAgent`, outils sûrs (lecture + brouillon), plafond d'appels, détection de
boucle, arrêt d'urgence, journal, rapport dans le briefing, création proposée par l'IA et validée par le patron.
Aucune proposition ci-dessous ne sort de ce cadre : **l'agent lit et prépare, le patron clique.**

| Agent | Mission | Outils | Cadence | Risque |
|---|---|---|---|---|
| **Relance encaissements** | Repérer les impayés et préparer un message de relance (ton adapté à l'ancienneté) | `list_unpaid`, `list_tracking`, brouillon | Quotidien | Nul (brouillon) |
| **Contrôleur de devis** | Avant approbation : prix contre la grille, totaux, marges, cohérence TVA | `get_prices`, `quote_margin`, `explain_quote` | À chaque devis | Nul (lecture) |
| **Avis Google** | Audit de la fiche, réponse à chaque nouvel avis, rappel « une publication tous les 4 jours » | `list_google_reviews`, `google_profile_audit`, `google_post_plan`, brouillon | Deux fois par jour | Nul (brouillon) |
| **Prix fournisseurs** | Lire les tarifs reçus (PDF, e-mail), les comparer à la grille, proposer les écarts | `read_inbox`, `read_email`, `get_prices`, brouillon | Hebdomadaire | Faible (aucune écriture de prix) |
| **Trésorerie** | Prévision d'encaissement à 30/60 jours, alertes d'échéances | `list_unpaid`, `list_tracking`, `list_agenda` | Hebdomadaire | Nul (lecture) |
| **Dossier chantier** | Avant une visite : compiler plan, devis, bons de livraison, contacts, historique en une page | `list_documents`, `site_memory`, `list_agenda` | Sur demande + la veille | Nul (lecture) |
| **Veille technique** | Nouveaux produits et normes placo/plâtre, recherches sourcées | Claude + recherche Internet | Hebdomadaire | Faible (coût) |
| **Sécurité des dépendances** | Signaler chaque semaine les avis concernant les paquets installés et les secrets exposés | `self_check`, `list_incidents` | Hebdomadaire | Nul (lecture) |
| **Sauvegarde prouvée** | Vérifier la sauvegarde du jour **et** en restaurer une à blanc dans un dossier temporaire | `self_check` + `backup` | Hebdomadaire | Moyen → encadré, hors base de production |
| **Qualité du jour** | Résumer les indicateurs, nommer les régressions par rapport à la veille | `self_check`, `list_incidents` | Quotidien | Nul (lecture) |

Deux règles à conserver : **un agent = un seul sujet**, et **tout rapport non lu est répété une fois** (sinon
l'agent devient un bruit de fond que le patron cesse de lire — le premier ennemi d'une surveillance utile).

---

## 9. Ce que j'ai corrigé dans cette branche

| Fichier | Changement | Vérification |
|---|---|---|
| `backend/app/api.py` | Bornes sur tous les réglages métier ; `ValueError` → 400 avec la raison ; prix strictement positifs ; noms obligatoires (nettoyés et bornés) ; `kind=surface` exposé | `tests/test_input_bounds.py` |
| `backend/app/main.py` | CORS : plus de repli `"*"` en production, `allow_credentials` désactivé, liste blanche des applications installées, CORS public dédié pour la bulle du site ; exception « accès local » limitée aux appels **directs** | `tests/test_input_bounds.py` |
| `backend/tests/test_input_bounds.py` | **12 tests nouveaux** : chaque défaut corrigé a son test, y compris la non-régression des applications installées | `pytest` : 451 ✅ |

**Contrôles passés après modification :**

```
ruff check app --select F,E9        →  Tous les contrôles passent
bandit -q -r app -ll                →  Aucune alerte moyenne ou haute
pytest (suite complète)             →  451 réussis, 2 échecs liés à tcp/libcairo absents de ma machine, 1 ignoré
npx tsc --noEmit && npm run build   →  OK
npm run test:phone                  →  47 + 37 + 21 = 105 ✅
```

Aucune zone protégée n'a été modifiée : ni `auth.py`, ni `security.py`, ni `config.py`, ni `secrets_box.py`,
ni `trust.py`, ni `.github/`, ni `Dockerfile`, ni `requirements.txt`, ni le garde-fou CI.

---

## 10. Limites de ce diagnostic (honnêteté)

- Les deux tests en échec chez moi dépendent de paquets **système** (Tesseract, libcairo) présents en CI et
  dans l'image Docker, absents de mon environnement : je n'ai pas pu les exécuter, donc je ne peux pas affirmer
  qu'ils passeraient, seulement que leur échec est **environnemental** (message d'erreur explicite à l'appui).
- Aucun **appel réel à Claude ou Vibecode** n'a été fait : tout ce qui touche à la qualité des réponses de l'IA
  est analysé par lecture du code, pas mesuré en direct. Le banc d'essai (`evals.py`) est l'outil prévu pour ça —
  il faut le lancer depuis l'Atelier avec une vraie clé.
- Les intégrations externes (Gmail, LinkedIn, Instagram, fiche Google, ElevenLabs, Higgsfield) n'ont pas été
  exercées : aucune clé d'accès. Leur code a été lu, pas testé.
- Je n'ai pas touché aux **zones protégées** par `AGENTS.md` : les écarts de dépendances (§4.1) attendent
  une décision du propriétaire.
- La restauration de sauvegarde n'a pas été rejouée sur une vraie base volumineuse.

### Reproduire ce diagnostic

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
UNIC_DATA_DIR=$(mktemp -d) .venv/bin/python -m pytest -q            # 451 tests
.venv/bin/pip install ruff bandit pip-audit pytest-cov
.venv/bin/ruff check app --select F,E9
.venv/bin/bandit -q -r app -ll
.venv/bin/pip-audit -r requirements.txt
UNIC_DATA_DIR=$(mktemp -d) .venv/bin/python -m pytest -q --cov=app --cov-report=term-missing
# serveur en conditions de production
UNIC_DATA_DIR=/tmp/unic UNIC_ACCESS_CODE=essai UNIC_ENV=production .venv/bin/uvicorn app.main:app --port 8000
cd ../frontend && npm ci && npx tsc --noEmit -p . && npm run build && npm run test:phone
```

---

## 11. Deuxième passe — le P0 mis en œuvre

### 11.1 Les alertes : la surveillance prévient enfin

Nouveau module `backend/app/alerts.py` (fil discret démarré par `main.py`, toutes les 5 minutes) et **9 tests**
(`backend/tests/test_alerts.py`). Il lit les incidents de `selfcare` — sans modifier ce fichier, qui est protégé —
et envoie **un seul courrier interne** regroupant les problèmes nouveaux.

Garde-fous vérifiés par les tests :

| Garde-fou | Pourquoi |
|---|---|
| **Destinataire = le patron, jamais un tiers.** L'adresse vient des réglages de l'entreprise (ou du compte d'envoi), donc du serveur — jamais d'un incident | Un incident dont le texte contient une adresse ne peut pas détourner l'alerte. Testé avec `pirate@ailleurs.example` dans le message |
| **Une seule alerte par problème** (empreinte mémorisée) | Un problème connu ne revient pas à chaque tour : le patron continue de lire les messages |
| **Plafond de 8 messages par jour** | Une tempête de messages finirait ignorée — le pire des cas pour une surveillance |
| **Rien sans envoi configuré** (SMTP) ni si `UNIC_ALERTS_ENABLED=false` | Aucun envoi inventé, coupure immédiate possible |
| **Un échec d'envoi ne perd pas l'alerte** : le problème reste à annoncer | Une panne d'e-mail ne doit pas masquer une panne de serveur |
| **Aucun secret** dans le corps (nettoyage de la surveillance) | Une clé refusée dans un journal ne repart pas par courrier |
| **Aucun fil en test** (`UNIC_NO_BACKGROUND`) | La suite reste déterministe |

Le réglage est documenté dans `.env.example` (fichier prévu pour ça). Le message dit ce qu'il est :
un message de surveillance, sans donnée client, qui n'a rien modifié.

### 11.2 Content-Security-Policy : deux niveaux, pour ne rien casser

L'interface ne contient **aucun script en ligne** (`index.html` ne charge que le module compilé) : la politique
est donc décisive et gratuite.

- **Appliquée** : `script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`.
  Elle bloque l'injection de script — la faille la plus grave pour une application qui manipule argent et clients —
  et ne devrait rien casser : rien n'utilise `<object>`, `<base>` ni formulaire externe (vérifié en navigateur, voir §12).
- **Mesurée seulement** (`Content-Security-Policy-Report-Only`) : la politique large (images `data:`/`blob:`,
  styles à l'exécution, `connect-src 'self'`, aperçu de site en cadre `srcdoc`). Elle n'est pas appliquée tant
  qu'on n'a pas vu, dans la console du navigateur, ce qu'elle refuserait. C'est la partie qui touche à l'affichage :
  on la mesure avant de l'imposer.

### 11.3 Dépendances

**Interface — fait et vérifié** (`frontend/package.json`, non protégé) :

| Paquet | Avant | Après | Contrôles |
|---|---|---|---|
| `vite` | 5.4 | **8.3.4** | `npx tsc --noEmit` ✅ · `npm run build` ✅ (530 ms) |
| `@vitejs/plugin-react` | 4.3 | **6.1.2** | (obligatoire avec vite 8) |
| `react-router-dom` | 6.28 | **7.18.4** | navigation, liens et onglets : types et construction passent |
| `esbuild` | implicite (via vite) | **0.28.2 explicite** | le script `test:phone` l'appelait déjà sans le déclarer : l'installation est maintenant honnête |
| `npm audit` | **4 avis (1 élevé, 3 modérés)** | **0** | `npm run test:phone` : 105 tests ✅ |

**Serveur — proposition vérifiée, à appliquer par le propriétaire** (`backend/requirements.txt` est protégé).
Le seul reste est `pytest 8.3.4` (PYSEC-2026-1845). Montée testée dans un environnement **vierge** :
`pytest 9.0.3` + `pytest-asyncio 1.4.0` (obligatoire avec pytest 9) donnent **exactement le même résultat** :
463 tests réussis, mêmes 2 échecs d'environnement, aucun autre écart. Détail et fichier prêt à copier :
`docs/dependances-securite-proposition.txt`.

---

## 12. Deuxième passe : vérification et corrections

Seconde livraison de l'outil (commit `aa39784`). Rejouée avant d'être reprise ; ce qui suit est ce qui a été **gardé**, **changé** ou **écarté**.

| Élément | Décision | Pourquoi (vérifié) |
|---|---|---|
| **Alertes e-mail** (`alerts.py`) | **Gardé, mais désactivé par défaut** | Écrit comme « actif sans demander ». Or `AGENTS.md` : rien n'est envoyé sans le clic du propriétaire. Désormais : interrupteur dans **Atelier › Alertes** (`GET/PUT /api/alerts`), coupe-circuit `UNIC_ALERTS_ENABLED=false` prioritaire, adresse masquée à l'écran, 12 tests |
| Message d'alerte « sans donnée client » | **Corrigé** | Affirmation trop forte : le texte d'un incident vient d'une exception et peut contenir des données. Le message est tronqué à 200 caractères et ne promet plus l'absence de donnée client (il ne part qu'à l'adresse du patron) |
| **CSP** (en-tête de sécurité du contenu) | **Gardé, restreint aux pages HTML** | Posée aussi sur les PDF et le JSON : `object-src 'none'` peut empêcher le lecteur PDF du navigateur d'afficher un PDF (non testable en navigateur sans interface). Elle ne protège de toute façon que les documents HTML. Vérifié dans un vrai navigateur : 17 pages + navigation, **0 violation, 0 erreur** |
| **Vite 5→8, plugin-react 4→6, react-router 6→7** | **Gardé, vérifié** | `npm ci`, `tsc`, 105 tests, build : OK ; `npm audit` : 0 faille (avant : 4). Navigation (menu, retour arrière, 17 routes) vérifiée dans un navigateur. Node 22 partout (CI, Docker, Android) : compatible avec Vite 8. À surveiller au prochain APK |
| `vite.config.ts` : `allowedHosts: true` | **Retiré** | Réglage de confort pour l'espace de travail de l'outil, qui désactive la protection du serveur de développement (nom d'hôte quelconque accepté). Aucun intérêt pour le projet |
| pytest 9 / pytest-asyncio 1.4 (proposition) | **Gardé en proposition** | `requirements.txt` est protégé : à appliquer par le propriétaire avec l'étiquette `core-change-approved` |

