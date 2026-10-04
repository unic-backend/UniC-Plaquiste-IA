"""Plateformes sociales UniC : limites, conseils, état honnête des connexions."""
from __future__ import annotations

# publication automatique : aucune plateforme n'est branchée à une API (OAuth requis).
PLATFORMS: dict[str, dict] = {
    "linkedin": {"label": "LinkedIn", "max": 3000,
                 "desc": "Réseau pro B2B — chantiers, savoir-faire, recrutement.",
                 "tip": "Ton pro, carrousel photos chantier, CTA contact UniC."},
    "facebook": {"label": "Facebook", "max": 2000,
                 "desc": "Page entreprise — audience locale Sénégal.",
                 "tip": "Photos nettes, lieu (Dakar / Diamniadio), appel à devis."},
    "instagram": {"label": "Instagram", "max": 2200,
                  "desc": "Visuel — finitions, cloisons, plafonds.",
                  "tip": "Hashtags locaux + métier, 1 accroche courte."},
    "tiktok": {"label": "TikTok", "max": 2200,
               "desc": "Vidéos courtes process pose / tips.",
               "tip": "Hook 3 s, texte à l'écran, musique libre."},
    "youtube": {"label": "YouTube", "max": 5000,
                "desc": "Vidéos longues — méthodes, témoignages.",
                "tip": "Titre clair + description avec contact UniC."},
    "reddit": {"label": "Reddit", "max": 40000,
               "desc": "Communautés (BTP, DIY) — pas de spam promo.",
               "tip": "Respecter les règles du sub ; valeur d'abord."},
    "x": {"label": "X (Twitter)", "max": 280,
          "desc": "Annonces courtes et actualités.",
          "tip": "Une idée = un post, lien site ou WhatsApp."},
    "whatsapp": {"label": "WhatsApp Business", "max": 1000,
                 "desc": "Statuts et messages clients (broadcast).",
                 "tip": "Consentement destinataires ; pas de spam."},
    "pinterest": {"label": "Pinterest", "max": 500,
                  "desc": "Inspiration finitions et ambiances.",
                  "tip": "Image verticale + description SEO simple."},
    "google_business": {"label": "Fiche Google (Maps)", "max": 1500,
                        "desc": "Fiche Google Maps — actualités, offres, réponses aux avis.",
                        "tip": "Mots-clés métier + ville, appel à l'action, réponse polie aux avis."},
    "website": {"label": "Site web", "max": 5000,
                "desc": "Textes de pages et articles du site UniC.",
                "tip": "Un sujet par page, ville + métier dans le titre."},
}

STATUSES = ("draft", "review", "approved", "published")
NEXT_STATUS = {"draft": "review", "review": "approved", "approved": "published"}
AUTO_PUBLISH_NOTE = (
    "Publication automatique NON DISPONIBLE : aucune API plateforme n'est configurée. "
    "Copiez le texte approuvé, publiez-le vous-même, puis cliquez « Marquer publié »."
)


def check_post(platform: str, body: str, hashtags: str = "") -> str | None:
    """Message d'erreur si le texte dépasse la limite de la plateforme, sinon None."""
    spec = PLATFORMS.get(platform)
    if spec is None:
        return "Plateforme inconnue"
    full = (body + ("\n\n" + hashtags if hashtags else "")).strip()
    if not body.strip():
        return "Texte vide"
    if len(full) > spec["max"]:
        return f"{spec['label']} : {len(full)} caractères, maximum {spec['max']}"
    return None
