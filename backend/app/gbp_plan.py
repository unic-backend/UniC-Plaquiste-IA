"""Fiche Google : régularité (une publication avec photo au moins tous les 4 jours) et référencement local.

Rien ne se publie ici : le module prépare (brouillon, photo à prendre, mots-clés) et suit le rythme. Publier = le patron colle
le texte et la photo dans Google (ou l'API quand elle sera accordée par Google). Aucune promesse de classement : le rang dépend
de la pertinence, de la proximité et de la notoriété ; ici on travaille les deux premiers et l'activité.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import assistant
from app.models import AppSetting, SocialPost

PLATFORM = "google_business"
CADENCE_DAYS = 4

#: thèmes en rotation : pas deux fois le même d'affilée
THEMES = [
    ("realisation", "Une réalisation récente", "Présente un chantier terminé : ce qui a été posé (faux plafond, cloison, moulure, peinture), le résultat."),
    ("avant_apres", "Avant / après", "Raconte la transformation d'une pièce en deux temps ; invite à voir les photos."),
    ("conseil", "Un conseil de pro", "Un conseil utile et vrai sur le plâtre, le BA13, l'humidité, l'entretien ou le choix d'un plafond."),
    ("offre", "Demander un devis", "Invite à demander un devis gratuit ; dis comment (appel, WhatsApp) ; rien d'inventé sur les prix."),
    ("coulisses", "Dans les coulisses", "Montre le savoir-faire : outils, étapes de pose, équipe au travail."),
    ("zone", "Zones d'intervention", "Cite les quartiers et villes où UniC intervient et le type de travaux."),
]

KEYWORDS = {
    "metier": ["faux plafond", "faux plafond BA13", "plaquiste", "cloison sèche", "cloison BA13", "plâtrerie", "moulure plafond",
               "plafond décoratif", "rénovation intérieure", "peinture intérieure", "décoration intérieure", "isolation plafond"],
    "zones": ["Dakar", "Almadies", "Mermoz", "Sacré-Cœur", "Plateau", "Médina", "Ouakam", "Ngor", "Yoff", "Point E", "Fann",
              "Liberté", "Parcelles Assainies", "Diamniadio", "Saly", "Mbour", "Thiès"],
    "recherches": ["plaquiste Dakar", "faux plafond Dakar", "cloison sèche Dakar", "devis faux plafond Dakar",
                   "rénovation appartement Dakar", "plafond BA13 Dakar", "décoration plafond Dakar", "plâtrier Dakar"],
    "categories": ["Plâtrier (catégorie principale à vérifier dans ta fiche)", "Entrepreneur en rénovation", "Décorateur d'intérieur",
                   "Entrepreneur en peinture", "Entrepreneur en construction"],
}

CHECKLIST = [
    ("categorie", "Catégorie principale = Plâtrier ; catégories secondaires ajoutées"),
    ("description", "Description (750 caractères) avec métier + Dakar + services"),
    ("services", "Liste des services remplie (faux plafond, cloison, moulure, peinture…)"),
    ("zones", "Zones desservies renseignées (quartiers de Dakar, Diamniadio…)"),
    ("horaires", "Horaires, téléphone, site web et WhatsApp à jour"),
    ("logo", "Logo et photo de couverture mis"),
    ("photos", "Au moins 15 photos de chantiers (nouvelle photo tous les 4 jours)"),
    ("questions", "5 questions-réponses ajoutées (délais, devis gratuit, zones…)"),
    ("avis", "Chaque avis reçoit une réponse sous 48 h"),
    ("demande_avis", "Lien de demande d'avis envoyé à chaque client satisfait"),
]


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _posts(db: Session):
    return db.query(SocialPost).filter(SocialPost.platform == PLATFORM, SocialPost.kind == "post")


def _setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def checklist(db: Session) -> dict:
    try:
        done = set(json.loads(_setting(db, "gbp_checklist") or "[]"))
    except json.JSONDecodeError:
        done = set()
    items = [{"id": k, "label": v, "done": k in done} for k, v in CHECKLIST]
    return {"items": items, "done": sum(1 for i in items if i["done"]), "total": len(items)}


def set_check(db: Session, item_id: str, value: bool) -> dict:
    if item_id not in dict(CHECKLIST):
        raise ValueError("Point inconnu")
    try:
        done = set(json.loads(_setting(db, "gbp_checklist") or "[]"))
    except json.JSONDecodeError:
        done = set()
    (done.add if value else done.discard)(item_id)
    row = db.get(AppSetting, "gbp_checklist")
    if row:
        row.value = json.dumps(sorted(done))
    else:
        db.add(AppSetting(key="gbp_checklist", value=json.dumps(sorted(done))))
    db.commit()
    return checklist(db)


def next_theme(db: Session) -> tuple[str, str, str]:
    last = _posts(db).order_by(SocialPost.created_at.desc()).first()
    keys = [t[0] for t in THEMES]
    idx = (keys.index(last.external_id.removeprefix("theme:")) + 1) % len(THEMES) if last and last.external_id.startswith("theme:") \
        and last.external_id.removeprefix("theme:") in keys else 0
    return THEMES[idx]


def plan(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    last = _posts(db).filter(SocialPost.status == "published").order_by(SocialPost.published_at.desc()).first()
    last_at = _utc(last.published_at) if last else None
    due_at = (last_at + timedelta(days=CADENCE_DAYS)) if last_at else now
    days_since = (now - last_at).days if last_at else None
    draft = _posts(db).filter(SocialPost.status != "published").order_by(SocialPost.created_at.desc()).first()
    month = _posts(db).filter(SocialPost.status == "published", SocialPost.published_at >= now - timedelta(days=30)).count()
    theme = next_theme(db)
    return {
        "cadence_days": CADENCE_DAYS, "last_published_at": last_at.isoformat() if last_at else None, "days_since": days_since,
        "due": due_at <= now, "next_due_at": due_at.isoformat(), "published_last_30_days": month,
        "target_last_30_days": 30 // CADENCE_DAYS, "theme": {"id": theme[0], "label": theme[1]},
        "draft": {"id": draft.id, "title": draft.title, "body": draft.body, "photo_brief": draft.photo_brief, "status": draft.status} if draft else None,
        "checklist": checklist(db), "keywords": KEYWORDS,
        "auto_publish": False,
        "auto_publish_note": ("Publication automatique NON DISPONIBLE : elle exige l'accès « API Google Business Profile », "
                              "accordé par Google sur demande. En attendant : tu copies le texte et tu ajoutes la photo en 20 secondes."),
    }


def _recent_openings(db: Session, n: int = 5) -> list[str]:
    return [p.body[:90].replace("\n", " ") for p in _posts(db).order_by(SocialPost.created_at.desc()).limit(n).all()]


def generate_draft(db: Session, topic: str = "", memory: str = "") -> SocialPost:
    """Brouillon de la publication du jour + photo à prendre. Texte réel (jamais de chiffre ni de référence inventés)."""
    if not assistant.ai_available():
        raise RuntimeError("Claude n'est pas disponible : impossible de rédiger.")
    tid, tlabel, tbrief = next_theme(db)
    kws = ", ".join(KEYWORDS["recherches"][:5] + KEYWORDS["metier"][:4])
    system = (
        f"{assistant._BASE} Tu écris la publication de la fiche Google Maps d'UniC Plaquiste (Dakar). "
        "Réponds UNIQUEMENT en JSON : {\"texte\":\"...\",\"photo\":\"...\"}. "
        "texte : 500 à 900 caractères, accroche courte, 2 ou 3 mots-clés placés naturellement (jamais une liste de mots-clés), "
        "un lieu de Dakar si le sujet s'y prête, une phrase d'appel (appeler ou écrire sur WhatsApp pour un devis gratuit). "
        "N'invente aucun prix, chiffre, délai, nom de client ni chantier précis : parle du savoir-faire et de ce que le patron fournit. "
        "photo : UNE consigne claire de la photo à prendre aujourd'hui sur un chantier (angle, lumière, ce qu'on doit voir), en 1 phrase."
    )
    user = (f"Thème du jour : {tlabel} — {tbrief}\nSujet précisé par le patron : {topic or 'aucun'}\n"
            f"Mots-clés utiles : {kws}\nNe commence pas comme ces publications récentes : {_recent_openings(db) or 'aucune'}")
    out = assistant._ask(system, user, memory=memory)
    if not out:
        raise RuntimeError("L'IA n'a rien produit. Réessaie.")
    m = re.search(r"\{.*\}", out, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    text = (data.get("texte") or "").strip() or out.strip()
    if len(text) > 1500:
        text = text[:1497].rstrip() + "…"
    post = SocialPost(platform=PLATFORM, kind="post", title=tlabel, body=text, external_id=f"theme:{tid}",
                      photo_brief=(data.get("photo") or "").strip()[:500])
    db.add(post)
    db.commit()
    return post


def mark_done(db: Session, post_id: str, url: str = "") -> SocialPost:
    p = db.get(SocialPost, post_id)
    if p is None or p.platform != PLATFORM or p.kind != "post":
        raise LookupError("Publication introuvable")
    if not p.body.strip():
        raise ValueError("Publication vide")
    p.status = "published"
    p.published_at = datetime.now(timezone.utc)
    p.external_url = (url or "")[:512]
    db.commit()
    return p


def optimize(db: Session, memory: str = "") -> dict:
    """Description, services, questions-réponses et catégories à coller dans la fiche (à valider par le patron)."""
    if not assistant.ai_available():
        raise RuntimeError("Claude n'est pas disponible : impossible de rédiger.")
    system = (
        f"{assistant._BASE} Tu optimises la fiche Google Maps d'UniC Plaquiste (Dakar) pour le référencement local. "
        "Réponds UNIQUEMENT en JSON : {\"description\":\"...\",\"services\":[{\"nom\":\"...\",\"texte\":\"...\"}],"
        "\"questions\":[{\"q\":\"...\",\"r\":\"...\"}],\"categories\":[\"...\"]}. "
        "description : 700 à 750 caractères, métier + Dakar + services, naturelle, sans promesse chiffrée. "
        "services : 8 services (faux plafond BA13, cloison sèche, moulures, peinture, rénovation…) avec 1 phrase chacun. "
        "questions : 5 questions que les clients posent, réponses honnêtes (devis gratuit si c'est vrai pour UniC, zones, contact) "
        "sans inventer de délai ni de prix. categories : catégorie principale puis 3 secondaires. "
        "N'invente aucune distinction, aucun chiffre, aucune année d'expérience."
    )
    out = assistant._ask(system, f"Mots-clés : {json.dumps(KEYWORDS, ensure_ascii=False)}", memory=memory)
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    if not data.get("description"):
        raise RuntimeError("L'IA n'a pas produit de fiche exploitable. Réessaie.")
    data["description"] = data["description"].strip()[:750]
    return data
