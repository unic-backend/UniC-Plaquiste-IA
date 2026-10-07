"""Lettre d'accompagnement d'un devis approuvé (250 mots maximum), partagée avec le PDF."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import assistant, memory as mem
from app.models import Quotation
from app.services import company_dict


def make_cover_letter(db: Session, q: Quotation) -> str:
    co = company_dict(db)
    client = (q.customer.contact_name or q.customer.name) if q.customer else (q.client_label or "")
    args = (client, q.number, q.object_text or q.title or "", q.site_location or "", q.total, q.currency, q.validity_days or 30,
            co.get("phone") or "", co.get("email") or "")
    if not assistant.ai_available():
        return assistant.cover_letter_fallback(*args)
    items = [it.description for it in sorted(q.items, key=lambda x: x.position)]
    return assistant.draft_cover_letter(args[0], args[1], args[2], args[3], items, *args[4:],
                                        memory=mem.block(db, q.object_text or q.title or "devis"))


def ensure_cover_letter(db: Session, q: Quotation) -> None:
    """À l'approbation : prépare la lettre si elle n'existe pas. Un échec de rédaction ne bloque jamais l'approbation."""
    if q.cover_letter:
        return
    try:
        q.cover_letter = make_cover_letter(db, q)
    except Exception:
        pass
