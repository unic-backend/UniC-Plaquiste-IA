"""Nettoyage de la boîte : repère pubs, newsletters et notifications GitHub déjà traitées, SANS rien supprimer.

- Règles fixes (aucun appel IA, aucun coût, résultat prévisible et testable).
- Prudence d'abord : tout ce qui ressemble à du travail (devis, facture, paiement, chantier, rendez-vous…) n'est JAMAIS proposé,
  ni une alerte GitHub utile (échec, relecture demandée, mention).
- L'IA et les agents n'ont aucun accès à cette action : seul le clic du patron envoie à la corbeille de Gmail (récupérable 30 jours).
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import InboxMessage

#: ce qui ressemble à du travail ou à de l'argent : jamais proposé
_KEEP = re.compile(r"\b(devis|facture|factur\w*|paiement|r[ée]glement|virement|acompte|chantier|commande|contrat|rdv|rendez-vous|visite|"
                   r"livraison|re[çc]u|quote|invoice|payment)\b", re.I)
#: notification GitHub à garder (action attendue ou problème)
_GH_KEEP = re.compile(r"(failed|failing|failure|[ée]chec|requested your review|review requested|mentioned you|assigned you|"
                      r"changes requested|security alert|vulnerab)", re.I)
#: notification GitHub terminée
_GH_DONE = re.compile(r"(merged|closed|succeeded|passed|was successful|fusionn|ferm[ée])", re.I)
_PROMO_SUBJECT = re.compile(r"(\bpromo\w*|-\s?\d+\s?%|\d+\s?%\s?(de )?(r[ée]duction|off)|offre sp[ée]ciale|soldes?|vente flash|"
                            r"code promo|newsletter|bon plan|derni[èe]res? (heures|chances?)|black friday|gratuit)", re.I)
_UNSUB = re.compile(r"(se d[ée]sabonner|d[ée]sinscri\w+|unsubscribe|ne plus recevoir|g[ée]rer (mes|vos) pr[ée]f[ée]rences)", re.I)
_BULK_SENDER = re.compile(r"^(no[-_.]?reply|newsletter|news|marketing|promo\w*|offres?|info|infos|contact|hello|bonjour|deals?|mailing)", re.I)


def classify(m: InboxMessage) -> tuple[str, str] | None:
    """(catégorie, raison) si le mail peut être proposé au nettoyage, sinon None."""
    sender = (m.from_addr or "").lower()
    subject, body = m.subject or "", m.body or ""
    if m.reply_draft_id or _KEEP.search(subject) or _KEEP.search(body[:600]):
        return None
    if sender.endswith("@github.com") or sender.endswith(".github.com"):
        text = f"{subject}\n{body[:1500]}"
        if _GH_KEEP.search(text):
            return None
        if _GH_DONE.search(text):
            return "GitHub", "Notification GitHub : déjà fusionnée, fermée ou réussie"
        return None
    local = sender.split("@", 1)[0]
    signals = int(bool(_UNSUB.search(body))) + int(bool(_PROMO_SUBJECT.search(subject))) + int(bool(_BULK_SENDER.match(local)))
    if signals >= 2:
        return "Publicité", "Publicité ou newsletter (désabonnement, offre, expéditeur automatique)"
    return None


def candidates(db: Session) -> list[dict]:
    out = []
    for m in db.query(InboxMessage).order_by(InboxMessage.fetched_at.desc()).limit(200).all():
        c = classify(m)
        if c:
            out.append({"id": m.id, "from_addr": m.from_addr, "subject": m.subject, "date": m.date, "category": c[0], "reason": c[1]})
    return out
