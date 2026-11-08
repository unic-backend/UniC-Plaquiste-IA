---
name: unic-factures
description: Factures et avoirs UniC Plaquiste à partir d'un devis, et suivi de ce qui reste à payer. À utiliser dès que le patron demande une facture, un avoir, « facture le devis », le reste à payer d'un client, ou la liste de ses devis et factures. Ne tourne jamais tout seul : seulement à la demande.
---

# Factures UniC (à la demande)

## 1. Lire avant tout
- Dépôt `unic-backend/unic-plaquiste-ia` (sinon demande au patron de l'ouvrir). `docs/MEMOIRE-CLAUDE.md` : règles du patron.
- Base de travail : `UNIC_DATA_DIR` d'une sauvegarde restaurée (voir `docs/PLAN-A-ET-B.md`) : ce sont les vrais devis et factures du patron. Sans sauvegarde restaurée, dis-le : tu ne peux pas facturer un devis que tu ne vois pas.

## 2. Retrouver le devis
```bash
python scripts/unic_facture.py liste
```
Montre au patron le devis trouvé (numéro, client, total). En cas de doute sur le client ou le devis : UNE question courte.

## 3. Vérifier avant de facturer
- Toutes les lignes du devis ont un prix (sinon l'outil refuse : fais compléter le devis d'abord, via l'agent devis).
- Montant, client, lieu : relis-les avec le patron. Jamais de prix, TVA ou taux inventé.
- Un devis déjà facturé : signale-le (la liste montre ses factures « …-F »), ne refais pas de doublon.

## 4. Créer la facture (après son « ok »)
```bash
python scripts/unic_facture.py depuis-devis UC-AAAA-XXXX-CLI          # facture : numéro du devis + « -F »
python scripts/unic_facture.py depuis-devis UC-AAAA-XXXX-CLI --avoir  # avoir : « -AV »
```
Brouillon + PDF, même numérotation que l'appli. Donne au patron le numéro, le total et le chemin du PDF.

## 5. Ramener au serveur
`python scripts/planb_export.py`, puis dans l'appli : Paramètres › Sauvegardes › « Importer un dossier de Claude ».

## Limites (le dire au patron)
- Versements, acomptes par tranche, bons de commande et de livraison : à faire dans l'appli (pas encore dans cet outil).

## Interdits
Rien ne part (e-mail, WhatsApp) sans le clic du patron. Jamais de montant inventé. Une facture = un devis existant.
