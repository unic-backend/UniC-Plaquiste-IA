"""Impayés : échéance de chaque facture, retards, relances. Calculs en code, montants sans décimales."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Invoice
from app.services import client_name_of, company_dict


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def due_date(db: Session, inv: Invoice, days: int | None = None) -> datetime | None:
    """Échéance enregistrée, sinon approbation (ou création) + délai de l'entreprise (anciennes factures)."""
    if inv.due_date:
        return _aware(inv.due_date)
    start = _aware(inv.approved_at or inv.created_at)
    if start is None:
        return None
    if days is None:
        days = int(company_dict(db).get("invoice_due_days") or 15)
    return start + timedelta(days=days)


def unpaid(db: Session, now: datetime | None = None) -> dict:
    """Factures approuvées avec un reste à payer, séparées : en retard / à venir. Les avoirs sont exclus."""
    now = now or datetime.now(timezone.utc)
    days = int(company_dict(db).get("invoice_due_days") or 15)
    late, soon = [], []
    for inv in db.query(Invoice).filter(Invoice.status.notin_(("draft", "paid", "cancelled"))).all():
        if inv.kind == "credit" or (inv.remaining or 0) <= 0:
            continue
        due = due_date(db, inv, days)
        row = {"id": inv.id, "numero": inv.number, "client": client_name_of(db, inv) or "Client", "reste": round(inv.remaining or 0),
               "devise": inv.currency or "FCFA", "echeance": due.date().isoformat() if due else None,
               "phone": getattr(inv.customer, "phone", None) if inv.customer else None}
        if due and due < now:
            row["jours_retard"] = (now - due).days
            late.append(row)
        else:
            row["jours_restants"] = (due - now).days if due else None
            soon.append(row)
    late.sort(key=lambda r: -r["jours_retard"])
    soon.sort(key=lambda r: r["echeance"] or "9999")
    return {"en_retard": late, "a_venir": soon, "total_retard": sum(r["reste"] for r in late),
            "total_a_venir": sum(r["reste"] for r in soon), "delai_jours": days}


def fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def reminder_text(row: dict, company: str = "UniC Plaquiste") -> str:
    """Relance polie, sans IA : chiffres exacts, aucune menace."""
    late = row.get("jours_retard")
    when = f"arrivée à échéance le {row['echeance']}" if row.get("echeance") else "en attente"
    return (f"Bonjour {row['client']},\n\nJe me permets de vous rappeler que la facture {row['numero']}, {when}"
            + (f" ({late} jour{'s' if late and late > 1 else ''} de retard)" if late else "")
            + f", présente un reste à payer de {fmt(row['reste'])} {row['devise']}.\n\n"
            "Merci de me confirmer la date de règlement. Je reste disponible pour toute question.\n\n"
            f"Cordialement,\n{company}")
