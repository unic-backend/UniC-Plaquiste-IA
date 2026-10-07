# Demande d'accès à l'API Google Business Profile (publication automatique)

> Je ne peux pas déposer cette demande à ta place : elle exige ton compte Google. Tout est prêt à copier.
> Les étapes et noms de pages viennent de la documentation Google (developers.google.com/my-business) ; Google les modifie
> parfois. Le délai de réponse n'est pas garanti.

## Avant de commencer
- Ta fiche Maps est **validée** (vérifiée) et active depuis un moment (Google demande une fiche établie ; à vérifier dans leur page « Prerequisites »).
- Tu as le compte Google propriétaire de la fiche (unicplaquiste@gmail.com).
- Sur téléphone : ouvre Chrome en « version ordinateur » (menu ⋮ → Site pour ordinateur).

## Étapes
1. **Projet Google Cloud** : console.cloud.google.com → créer un projet « UniC AI » → noter le **numéro du projet**.
2. **Formulaire d'accès** : page « Prerequisites » de l'API Business Profile (developers.google.com/my-business/content/prereqs) → lien « request access » → remplir avec le texte ci-dessous.
3. **Attendre la réponse de Google** (e-mail). Rien à faire d'ici là : la publication reste manuelle (20 secondes).
4. Une fois accepté : dans le projet, **activer** les API « My Business Account Management », « My Business Business Information » et « Google My Business ».
5. **OAuth** : écran de consentement (Externe, mode test, ajouter unicplaquiste@gmail.com comme testeur) → créer un identifiant « Application Web » avec l'URI de redirection `https://developers.google.com/oauthplayground`.
6. **Jeton** : OAuth Playground → roue crantée → « Use your own OAuth credentials » → portée `https://www.googleapis.com/auth/business.manage` → autoriser → échanger le code → copier le **refresh token**.
7. Donne-moi (ou saisis dans l'appli quand l'écran existera) : identifiant client, secret client, refresh token. Je retrouve l'identifiant de compte et de fiche.

## Texte de la demande (à coller dans le formulaire)
**Business:** UniC Plaquiste — drywall, false ceilings, partitions, painting and interior finishing, Dakar, Senegal
**Website:** https://www.unicplaquiste.com
**Google Business Profile:** https://maps.app.goo.gl/fKvNLhN1r3U88gsv9
**Contact e-mail:** unicplaquiste@gmail.com
**Google Cloud project number:** (à renseigner)

**Use case:**
UniC Plaquiste requests Basic API access for its own, single business location. We are building a private internal assistant
used only by the business owner to: (1) publish Google Posts with photos on our own listing about every 4 days, (2) read and
reply to customer reviews on our own listing, and (3) keep our own listing information (description, services, Q&A) up to date.
Every post and every reply is reviewed and approved by the owner before it is sent. We do not manage third-party listings, we do
not resell or share Business Profile data, and we store only an OAuth refresh token for the owner's account, encrypted on our server.
Expected volume: a few API calls per day.

## Ce qui change quand c'est accepté
- Le bouton **J'ai publié** devient **Publier** : le texte part directement sur ta fiche, après ton approbation.
- Les avis sont lus et les réponses publiées de la même façon (toujours après ton approbation).
