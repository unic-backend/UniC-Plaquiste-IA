---
name: unic-memoire
description: Retrouver dans quelle ancienne conversation Claude se trouve une information (un sujet, un client, un chiffre, un fichier, une décision) SANS relire les conversations une par une. À utiliser dès qu'Ousmane demande « on avait parlé de… », « retrouve la conversation où… », « je ne sais plus où j'ai mis… », « qu'est-ce qu'on avait décidé pour… ». Pour un devis ou une facture : compétence unic-archives d'abord.
---

# Mémoire des conversations UniC — recherche économe

## Règle n°1 : l'index d'abord, une seule fois
Lis UNIQUEMENT l'index Google Sheets « UniC_Index_Conversations » (Drive, id `1rhsqmflb7_sGQno4mI86HFXs8I6PMbltRPsF7OUucJk`).
Une ligne = un jour d'une conversation : jour, titre de la conversation, 1re demande du jour, mots-clés, noms cités, numéros de devis, fichiers joints.
Cherche le sujet dans les colonnes (mot exact, sans accent, synonymes : « placo » = « BA13 », « faux plafond » = « plafond »).

## Répondre
1. Donne les 1 à 3 meilleures lignes : titre de la conversation + jour + pourquoi elle correspond (mot-clé ou nom trouvé). 2 à 5 lignes en tout.
2. Ousmane peut alors ouvrir la conversation lui-même (barre de gauche › Rechercher › titre).
3. S'il veut le CONTENU exact : UNE seule recherche dans les conversations passées, ciblée sur le titre et le mot-clé trouvés dans l'index, jamais une fouille générale.
4. Rien dans l'index : dis-le en une ligne, et demande s'il veut UNE recherche dans les conversations (plus coûteuse) avec 2 ou 3 mots précis.

## Limites à dire franchement
- L'index couvre l'export du 10/11/2026 (conversations de juin à novembre 2026). Les conversations plus récentes n'y sont pas tant qu'Ousmane n'a pas refait un export.
- L'export ne contient pas le texte de certaines conversations (vides dans l'export) : elles n'y figurent pas.

## Mettre l'index à jour
Une fois par mois (ou quand Ousmane le demande) : Ousmane exporte ses données (claude.ai › Paramètres › Confidentialité › Exporter), envoie
`conversations-000.zip` dans une session Claude Code, et dit « mets à jour l'index des conversations ». Aucun outil ne peut lire les conversations tout seul.
