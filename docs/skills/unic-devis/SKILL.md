---
name: unic-devis
description: Devis, métré et liste de matériaux UniC Plaquiste (faux plafond, cloison BA13, peinture, décor). À utiliser dès que le patron demande un devis, un calcul de matériaux, un métré, des quantités, un prix de chantier, ou envoie des cotes, un plan ou une photo de pièce à chiffrer. Ne tourne jamais tout seul : seulement à la demande.
---

# Devis et matériaux UniC (à la demande)

Deux moteurs travaillent ensemble : le moteur d'UniC (règles du patron codées, grille de prix) et ton contre-calcul.
Tu ne recopies jamais le moteur sans vérifier.

## 0. Claude chat (sans dépôt ni scripts)
- Lis `PRIX-ET-REGLES.md` (dans cette compétence) AVANT tout chiffre : ce sont les SEULS prix permis. Jamais de prix « estimé ».
- Article absent de la grille = ligne « prix à donner par le patron », sans montant.
- Calcule comme `EXEMPLES.md` (méthode pas à pas du salon 5 × 4) : mêmes étapes, même ordre. Jamais « surface ÷ surface d'une plaque ».
- Résultat court : tableau matériaux, tableau main-d'œuvre, total, liste « Travail fini ». Pas de long texte.
- Pas de moteur ni de PDF ici : dis-le, et propose de faire le devis officiel dans l'appli UniC.

## Économie (règle du patron)
- Lis `PRIX-ET-REGLES.md` et `EXEMPLES.md` UNE fois par conversation. Rien d'autre : pas de recherche web, pas d'autres fichiers, pas d'autres compétences.
- Une cote manque : UNE question, puis tu calcules. Pas de variantes ni d'options non demandées.

## 1. Lire avant tout (Claude Code)
- Dépôt `unic-backend/unic-plaquiste-ia` (sinon demande au patron de l'ouvrir). `docs/MEMOIRE-CLAUDE.md` : prix en vigueur, règles du patron, méthode à deux moteurs.
- Base de travail : `UNIC_DATA_DIR` d'une sauvegarde restaurée = prix du jour (voir `docs/PLAN-A-ET-B.md`). Base neuve = grille du dépôt.

## 2. Comprendre la demande
- Pièces, cotes (longueur × largeur, hauteur), type (plafond dalle ou IPN, cloison 1 ou 2 faces, portes), décor, peinture.
- Une cote manque : pose UNE question courte. Ne devine jamais une cote, un prix, une TVA ou un taux.
- Plaques sans taille précisée = 2 m × 1,20 (règle du patron). Main-d'œuvre : prix au m² donné par le patron, jamais inventé.

## 3. Moteur UniC
```bash
python scripts/unic_calcul.py '<pièces JSON>' --main-oeuvre <prix_m2> --json
```
Types : `ceiling` (`support` dalle|ipn, `suspente_m`), `partition` (`height_m`, `sides`, `doors`), `paint` (`area_m2`, `coats`).

## 4. Contre-calcul (obligatoire)
Refais à la main, pièce par pièce : plan de pose des plaques (entières d'un mur à l'autre, morceaux comptés), fourrures (chutes raccordées : longueur totale ÷ 2,80), tiges (30 cm du mur puis 90 cm), cornières, montants (60 cm + 2 par jonction + 3 par porte), rails, vis (paquet de 1 000), chevilles (30 cm).
Écart → cherche la cause ; doute → demande au patron. Erreur du moteur → corrige le code avec un test (branche + PR).

## 5. Récapitulatif au patron (avant tout devis)
Tableau court : article, quantité, prix unitaire, total ; main-d'œuvre dans un tableau à part ; lignes sans prix signalées.
Livraison : prix donné par le patron ou « à la charge du client ».

## 6. Devis (seulement après son « ok »)
```bash
python scripts/unic_calcul.py '<pièces JSON>' --main-oeuvre <prix_m2> --devis "Client" --lieu "Quartier" [--objet "..."]
```
Crée le devis brouillon (numéro UniC, PDF) dans la base locale. Un travail = un seul devis ; une correction modifie le devis existant.
Pour le ramener dans l'appli : `python scripts/planb_export.py` puis Paramètres › Sauvegardes › « Importer un dossier de Claude ».

## Travail fini (à cocher avant de rendre, sinon on corrige d'abord)
- [ ] Un seul devis pour ce travail (une correction modifie l'existant).
- [ ] Matériaux et main-d'œuvre dans deux tableaux séparés ; main-d'œuvre = prix au m² du patron.
- [ ] Tous les prix viennent de `PRIX-ET-REGLES.md` (ou de la base) ; aucun prix, TVA ou taux inventé ni « estimé » ; lignes sans prix signalées.
- [ ] Mots du patron : « tige + pivot + cheville », jamais « suspente ».
- [ ] Plaques 2 m × 1,20 sauf ordre contraire ; barres 2,80 m ; vis par paquet de 1 000 ; bande en rouleau de 150 m.
- [ ] Contre-calcul fait, aucun écart inexpliqué avec le moteur ; totaux recalculés.
- [ ] Livraison : prix du patron ou « à la charge du client » ; moulures, colles, peinture seulement s'il les a demandées.

## Règle d'or
Une erreur signalée par le patron se corrige dans CE mode d'emploi (branche + PR), pas seulement dans le chat : sinon elle revient.

## Interdits
Rien ne part (e-mail, WhatsApp) sans le clic du patron. Jamais de prix inventé. Moulures, colles, peinture seulement s'il les demande.
