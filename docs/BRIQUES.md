# Briques open source et reprises d'ARENA : ce qui est repris, ce qui ne l'est pas, pourquoi

Mis à jour le 14/10/2026 (nuit de travail). Règle de ce document : **rien n'est annoncé comme vérifié sans l'être**. Les licences
marquées « annoncée » viennent de pages tierces (moteur de recherche), pas du fichier `LICENSE` du dépôt : **à vérifier dans le dépôt avant toute intégration**.

## 1. Ce qui est déjà repris d'ARENA (code du patron, « tous droits réservés » à son nom : il peut le réutiliser ici)

| Module ARENA | Dans UniC | PR |
|---|---|---|
| `core/execution/disjoncteur.py` | `backend/app/breaker.py` : après 3 échecs réels de suite, Gmail ou Google passent en pause 60 s (plus d'appels de 20 s répétés, plus de mot de passe refusé martelé chez Gmail). Visible dans l'Atelier. | breaker |
| `core/meetings/intelligence.py` | `backend/app/visit_report.py` + outil IA `visit_report` : compte rendu de visite sans rien inventer (mesures en code, « décidé » ≠ « proposé », responsable/échéance « non précisé » s'ils ne sont pas dits) | visit-report |
| `core/executive/calcul_affaires.py` + `risque_affaires.py` | `backend/app/business_calc.py` + outil IA `business_calc` : échéancier de paiement (somme **exacte**, ce qu'ARENA n'assurait pas), délai tenable, marge, « et si… », risque de concentration de clients calculé sur les vraies factures | business-calc |

### Déjà présent dans UniC (comparé, rien à recopier)

| Module ARENA | Équivalent UniC |
|---|---|
| `core/memory/contradiction.py` | `memory.conflicts` (divergences numériques, même sujet, même portée déclarée) |
| `core/relecture.py` (contrôle de prix avant réponse) | `pricecheck.review_reply`, appelé par l'orchestrateur sur chaque réponse |
| `core/executive/question_en_attente.py` | Inutile : UniC envoie tout l'historique de la conversation au modèle, « Medina » reste donc rattaché à la question du devis |

## 2. Ce qui n'est PAS repris, et pourquoi

| Brique | Raison |
|---|---|
| `agents/dioumtoukay` (agent qui entre dans un terminal et modifie des fichiers) | Exécuter des commandes sur le serveur de production est exactement ce que `AGENTS.md` interdit (zones protégées, rien ne part sans clic). L'Atelier d'UniC fait déjà le même travail **par pull request relue par le patron**. |
| MoneyPrinterTurbo (vidéos courtes automatiques ; licence MIT **annoncée**) | Demande ffmpeg, des clés de banques d'images et de la puissance de calcul : impossible sur l'hébergement actuel. Piste réaliste : le garder sur ta machine (ARENA le pilote déjà par HTTP) et n'ajouter à UniC qu'un appel HTTP optionnel, après ton accord. |
| VoiceStudio (AGPL-3.0), Netronome (GPL-2.0+), Edit-Banana (AGPL-3.0), CodeFormer (non commercial) | Licences incompatibles avec un produit commercial fermé : **jamais copiées**. ARENA les pilote par HTTP ou en sous-processus séparé ; c'est la seule manière correcte. |
| Tout ARENA en bloc (410 fichiers Python, Windows/Ollama/ffmpeg) | Autre pile, autre machine. Copier en bloc casserait la règle « ne sors pas de la base ». On reprend module par module, avec tests. |

## 3. Briques open source candidates (aucune installée : chaque ajout de dépendance touche `backend/requirements*`, zone protégée = ton accord)

| Brique | Utilité pour UniC | Licence (annoncée) | Coût / risque | Avis |
|---|---|---|---|---|
| **MarkItDown** (Microsoft) | Lire PDF, Word, Excel, PowerPoint en texte propre pour l'IA (plans, devis fournisseurs, courriers) | MIT | Dépendances optionnelles par format ; ne fait pas d'OCR dans les PDF | **Oui**, la plus utile : l'IA lit mieux les fichiers reçus |
| **Piper** (voix hors ligne) | Voix française gratuite sans clé ElevenLabs, sur le serveur ou l'appareil | MIT (moteur) ; **chaque voix a sa propre licence** | Modèles de voix à héberger (dizaines de Mo) ; qualité inférieure à ElevenLabs | Oui en secours quand ElevenLabs est coupé |
| **faster-whisper** | Transcription locale (visites de chantier dictées, appels) | MIT | Lourd en mémoire : à réserver à ta machine ou à un service séparé | Plus tard |
| **promptfoo** | Mesurer la qualité des réponses de l'IA à chaque changement | MIT | Outil de développement, pas du serveur | Utile pour `evals.py` |

Avant toute intégration : (1) ouvrir le fichier `LICENSE` du dépôt ; (2) lire la licence de chaque modèle/voix ; (3) refuser tout AGPL/GPL ; (4) tests ; (5) ton accord pour la dépendance.

## 4. Brief « portfolio Tega » (autre personne)

Repris : **la structure et les animations** (carte d'identité qui tombe et se retourne, mots en cascade, collage, chiffres qui montent, rangée de photos épinglée, mouvement réduit, impression PDF).
**Non repris** : le nom, le téléphone, l'e-mail, les photos, les chiffres et les textes de cette personne. Le Book d'UniC n'utilise que tes coordonnées, tes photos, tes chiffres déjà publiés sur ton site et tes 2 vrais avis Google (voir `backend/app/site_pages/book.html`, publiable depuis Réseaux › Site web › « Book d'entreprise »).

## 5. Skill « anti-vibecode » (Melvynx/shared-skills)

Repris : le **skill** (les **43 signes** d'un site « fait par l'IA » et son **scanner** `scripts/scan.mjs`, Node sans dépendance) dans `docs/anti-vibecode/` (le dossier `.claude/` est refusé par les garde-fous : Claude Code le lit sur demande, ou installé en global), et les mêmes règles envoyées aux **projets web de UniC Code** (`backend/app/anti_vibecode.py`, branché dans `code_tasks.start` ; un test vérifie que les deux copies restent identiques).
**Non repris** : rien d'autre du dépôt d'origine. **Licence non vérifiée** dans le dépôt d'origine : à contrôler avant toute diffusion hors de ce dépôt privé. Le design de l'appli UniC elle-même (`frontend/`) n'est pas réécrit.

## 6. Plugin « Ponytail » (DietrichGebert/ponytail, licence MIT)

Installé **sur le compte Claude du patron** (Paramètres › Plugins), pas dans le dépôt : `.claude/` est refusé par les garde-fous. Ses hooks ont été relus (v5.3.3) : pas de réseau actif, pas de lecture de secrets ; une mise à jour future n'est pas relue tant que la synchro automatique reste active.
Repris dans UniC Code : ses règles en bref (`LAZY_RULES` dans `backend/app/code_tasks.py`) sont ajoutées à **chaque projet** (dossier vide : `AGENTS.md` n'y arrive pas). Pour le code de l'appli, `AGENTS.md` dit déjà « étends l'existant, ne recrée rien » : rien n'est ajouté (`repair.py` est une zone protégée).
Premier résultat de son audit : `next_number` donnait le même numéro à deux requêtes simultanées (corrigé, test `test_numeros_simultanes.py`). Les devis et factures étaient déjà protégés par `add_with_unique_number` ; les clients, fournisseurs et projets ne l'étaient pas.
