# TikTok : accès API (publication depuis l'appli), à demander plus tard

État (documentation TikTok « Content Posting API », vérifiée le 04/10/2026) :
- **Direct Post** (`video.publish`) : tout contenu publié par une appli **non auditée** reste en visibilité **privée**. Un audit de conformité est requis pour lever la restriction.
- **Upload / brouillon** (`video.upload`) : la vidéo arrive dans la boîte de réception TikTok ; l'utilisateur doit toucher la notification et finaliser la publication dans TikTok. Le scope doit être approuvé et le compte doit avoir autorisé l'appli.
- Envoi du fichier : `FILE_UPLOAD` (PUT) ou `PULL_FROM_URL` (domaine vérifié obligatoire). Vidéo MP4 / H.264.

Ce que le patron peut faire aujourd'hui, sans API : l'appli écrit le script, la légende et les hashtags ; il filme, puis « Copier la légende et ouvrir TikTok ».

## Demande d'accès (à lancer seulement si le patron le veut)
1. developers.tiktok.com → se connecter avec le compte TikTok de l'entreprise → **Manage apps** → **Connect an app**.
2. Nom : UniC AI. Catégorie : outil de gestion de contenu. Site : https://www.unicplaquiste.com. Pages « Conditions » et « Confidentialité » : à publier sur le site (obligatoires).
3. Ajouter le produit **Content Posting API** ; demander `video.upload` (le plus simple à obtenir), puis `video.publish`.
4. Fournir une courte vidéo de démonstration : le patron écrit un script, filme, approuve, envoie en brouillon.
5. Délai de réponse non garanti ; refus possible. Rien n'est promis.

Texte d'usage (anglais) : « UniC Plaquiste is a single drywall and interior-finishing business in Dakar, Senegal. We build a private assistant used only by the business owner to prepare video scripts and upload the owner's own videos to the owner's own TikTok account as drafts. Every video is reviewed and approved by the owner before upload and the owner finalizes publication inside TikTok. We do not publish for third parties, we do not collect other users' data and we store only the owner's OAuth token, encrypted. »
