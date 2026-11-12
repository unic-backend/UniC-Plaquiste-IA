---
name: unic-archives
description: Retrouver un ancien devis ou une ancienne facture UniC Plaquiste (par client, lieu, date, montant ou numéro) SANS fouiller les anciennes conversations. À utiliser dès qu'Ousmane demande « le devis de… », « la facture de… », « combien j'avais facturé à… », « est-ce qu'il y a un devis pour… ». Lit un seul fichier, le registre.
---

# Archives UniC (devis et factures) — recherche économe

## Règle n°1 : un seul fichier
Lis UNIQUEMENT le registre Google Sheets « UniC_Registre_Devis_Factures » (Drive, id `19nw606ivjgom3kRyD-jEGwlmJfnJ40kv2cd34Frq_Q8`), une seule fois.
N'utilise PAS la recherche dans les anciennes conversations, ni Gmail, ni d'autres fichiers du Drive : c'est ce qui coûte cher.

## Répondre
1. Cherche dans le registre : client (prénom, nom, société, même approximatif : « Cecile » = « Cécile Diouf »), lieu, date, montant, numéro.
2. Réponds en 2 à 5 lignes : numéro, type, date, client, lieu ou objet, total, nom du PDF, conversation d'origine.
3. Colonne « Fiabilité du total » : « vérifié » se donne tel quel ; « probable » ou « à vérifier » se dit (« montant à confirmer sur le PDF »). Case vide : « montant non noté ». Ne jamais inventer un montant.
4. Plusieurs lignes possibles (ex. plusieurs devis Fast Group) : liste-les en une ligne chacune et demande lequel.
5. Rien trouvé : dis-le en une ligne et propose UNE seule recherche plus large (Drive : titre contenant le nom), seulement si Ousmane dit oui.

## Besoin du détail (lignes du devis, PDF)
Seulement si Ousmane le demande : ouvre le PDF nommé dans le registre (recherche Drive par titre exact), rien d'autre.

## Tenir le registre à jour
Après CHAQUE nouveau devis, facture ou avoir créé pour Ousmane (compétences unic-devis et unic-factures comprises) : propose d'ajouter la ligne au registre
(numéro, type, date, client, lieu / objet, total, « vérifié », nom du PDF, titre de la conversation). Une ligne corrigée : mets à jour le total et passe la fiabilité à « vérifié ».

## Travail fini (à cocher avant de rendre, sinon on corrige d'abord)
- [ ] Réponse tirée du registre (une seule lecture), avec le numéro UC- et la ligne source.
- [ ] Total « vérifié », « probable » ou « à vérifier » dit tel quel ; rien d'inventé.

## Règle d'or
Une erreur signalée par le patron se corrige dans CE mode d'emploi (branche + PR), pas seulement dans le chat : sinon elle revient.
