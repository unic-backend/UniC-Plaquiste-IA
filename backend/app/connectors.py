"""Actions des connecteurs (courrier, réseaux, fiche Google), partagées par l'API et par l'agent IA.

Règle : aucune fonction ici n'envoie un e-mail ni ne publie. Elles lisent ou préparent des brouillons ;
l'envoi et la publication restent des gestes explicites du patron (boutons Approuver / Envoyer / Publier).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import google_business as gbp, mailbox
from app.models import EmailDraft, InboxMessage, SocialPost
from app.social import PLATFORMS, check_post

logger = logging.getLogger("unic.connectors")


class ConnectorError(Exception):
    """Message lisible, affichable tel quel."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def sync_inbox(db: Session, limit: int = 20) -> dict:
    if not mailbox.imap_configured():
        raise ConnectorError("Lecture e-mail NON DISPONIBLE : IMAP non configuré.")
    try:
        rows = mailbox.fetch_recent(max(1, min(limit, 50)))
    except Exception as exc:
        logger.warning("IMAP échec : %s", exc)
        raise ConnectorError("Connexion à la boîte mail impossible. Vérifiez hôte, identifiant, mot de passe.", 502)
    known = {u for (u,) in db.query(InboxMessage.uid).all()}
    new = 0
    for r in rows:
        if r["uid"] in known:
            continue
        db.add(InboxMessage(**r))
        new += 1
    db.commit()
    return {"fetched": len(rows), "new": new}


def save_email_reply_draft(db: Session, mail: InboxMessage, body: str, subject: str = "", user_id: str | None = None) -> EmailDraft:
    body = (body or "").strip()
    if not body:
        raise ConnectorError("Réponse vide.", 400)
    subj = (subject or "").strip() or (mail.subject if mail.subject.lower().startswith("re:") else f"Re: {mail.subject}")
    d = EmailDraft(to_addr=mail.from_addr, subject=subj, body=body, status="draft",
                   related_type="inbox", related_id=mail.id, created_by=user_id)
    db.add(d)
    db.flush()
    mail.reply_draft_id = d.id
    db.commit()
    return d


def save_social_draft(db: Session, platform: str, body: str, hashtags: str = "", title: str = "",
                      kind: str = "post", in_reply_to: str = "", external_id: str = "") -> SocialPost:
    err = check_post(platform, body, hashtags)
    if err:
        raise ConnectorError(err, 400)
    p = SocialPost(platform=platform, kind=kind, title=title.strip(), body=body.strip(), hashtags=hashtags.strip(),
                   in_reply_to=in_reply_to.strip()[:5000], external_id=external_id)
    db.add(p)
    db.commit()
    return p


def require_google() -> None:
    if not gbp.configured():
        raise ConnectorError("Fiche Google NON DISPONIBLE : configuration incomplète (" + ", ".join(gbp.missing_settings()) + ").")


def google_call(fn, *args):
    require_google()
    try:
        return fn(*args)
    except gbp.GoogleError as exc:
        raise ConnectorError(str(exc), 502)


def valid_platform(platform: str) -> bool:
    return platform in PLATFORMS
