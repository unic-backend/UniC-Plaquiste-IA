"""Équipe et paie : ouvriers, journées ou tâches faites, avances et paies, reste dû.

Règles : les montants viennent du patron (tarif du jour de l'ouvrier, prix d'une tâche) — jamais devinés ; une journée sur un
chantier (devis accepté) devient aussi une dépense « main-d'œuvre » de ce chantier (rentabilité réelle, tracking.expenses) ;
la main-d'œuvre n'est jamais mélangée aux matériaux ; une erreur de saisie est annulée (gardée au journal), jamais effacée ;
rien n'est payé par l'appli : on note ce que le patron a remis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import tracking
from app.models import Expense, Quotation, Worker, WorkEntry, WorkerPayment, utcnow
from app.services import audit

MAX_AMOUNT = 1_000_000_000
PAY_KINDS = ("avance", "paie")


class TeamError(ValueError):
    """Message clair pour le patron."""


def _money(v, what: str = "Montant") -> float:
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError):
        raise TeamError(f"{what} invalide.")
    if not 0 < n <= MAX_AMOUNT or n != n:
        raise TeamError(f"{what} : il faut un nombre supérieur à zéro.")
    return n


def _when(d: datetime | None) -> datetime:
    d = d or utcnow()
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def find_worker(db: Session, name: str) -> Worker:
    """Retrouve L'ouvrier visé par son nom (sans accents ni casse). Plusieurs ou aucun → question au patron, jamais une devinette."""
    key = tracking.client_key(name)
    rows = [w for w in db.query(Worker).filter(Worker.active.is_(True)).all() if tracking.client_key(w.name) == key]
    if not rows:
        rows = [w for w in db.query(Worker).filter(Worker.active.is_(True)).all()
                if key and key != "sans-client" and key in tracking.client_key(w.name)]
    if not rows:
        raise TeamError(f"Aucun ouvrier « {name} » dans l'équipe : ajoute-le d'abord (nom, tarif du jour).")
    if len(rows) > 1:
        raise TeamError("Plusieurs ouvriers correspondent : " + ", ".join(w.name for w in rows) + ". Lequel ?")
    return rows[0]


def add_worker(db: Session, name: str, pay_mode: str = "jour", day_rate: float | None = None, phone: str = "", role: str = "",
               user_id: str | None = None) -> Worker:
    name = " ".join(str(name or "").split())[:255]
    if len(name) < 2:
        raise TeamError("Nom de l'ouvrier manquant.")
    if any(tracking.client_key(w.name) == tracking.client_key(name) for w in db.query(Worker).filter(Worker.active.is_(True)).all()):
        raise TeamError(f"« {name} » est déjà dans l'équipe.")
    mode = pay_mode if pay_mode in ("jour", "tache") else "jour"
    rate = _money(day_rate, "Tarif du jour") if day_rate not in (None, "", 0) else None
    w = Worker(name=name, pay_mode=mode, day_rate=rate, phone=str(phone or "")[:40], role=str(role or "")[:64])
    db.add(w)
    audit(db, user_id, "team_worker", "worker", name, f"{mode} {rate or ''}")
    db.commit()
    return w


def record_work(db: Session, worker: Worker, *, days: float | None = None, amount: float | None = None, label: str = "",
                quote: Quotation | None = None, day: datetime | None = None, user_id: str | None = None) -> dict:
    """Journée(s) au tarif du jour, ou tâche à prix donné. Sur un chantier : aussi une dépense « main-d'œuvre » de ce chantier."""
    if amount not in (None, "", 0):                          # tâche (ou journée à un prix exceptionnel dit par le patron)
        kind, units, total = "tache", 1.0, _money(amount)
        if days not in (None, "", 0):
            kind, units = "jour", _money(days, "Nombre de journées")
    else:
        units = _money(days if days not in (None, "", 0) else 1, "Nombre de journées")
        if units > 31:
            raise TeamError("Plus de 31 journées d'un coup : vérifie le nombre.")
        if not worker.day_rate:
            raise TeamError(f"Tarif du jour de {worker.name} inconnu : donne-le (ou le montant de ce travail), je ne le devine pas.")
        kind, total = "jour", round(units * worker.day_rate, 2)
    when = _when(day)
    what = label.strip()[:200] or (f"{units:g} journée(s)" if kind == "jour" else "Tâche")
    entry = WorkEntry(worker_id=worker.id, quotation_id=quote.id if quote else None, day=when, kind=kind, units=units,
                      amount=total, label=what, created_by=user_id)
    db.add(entry)
    db.flush()
    if quote is not None:   # la rentabilité du chantier voit ce travail (catégorie séparée des matériaux)
        e = Expense(quotation_id=quote.id, project_id=quote.project_id, label=f"{worker.name} — {what}"[:255], amount=total,
                    category="main-d'œuvre", currency=quote.currency or "", spent_at=when, created_by=user_id)
        db.add(e)
        db.flush()
        entry.expense_id = e.id
    audit(db, user_id, "team_work", "worker", worker.id, f"{worker.name} {kind} {units:g} = {total}" + (f" ({quote.number})" if quote else ""))
    db.commit()
    out = summary(db, worker)
    out["ajoute"] = {"id": entry.id, "type": kind, "unites": units, "montant": total, "libelle": what,
                     "chantier": quote.number if quote else None}
    return out


def record_payment(db: Session, worker: Worker, amount: float, kind: str = "paie", method: str = "", note: str = "",
                   paid_at: datetime | None = None, user_id: str | None = None) -> dict:
    """Ce que le patron a REMIS à l'ouvrier (l'appli ne paie rien). Une avance qui dépasse le travail fait est signalée."""
    total = _money(amount)
    kind = kind if kind in PAY_KINDS else "paie"
    p = WorkerPayment(worker_id=worker.id, amount=total, kind=kind, method=str(method or "")[:64], note=str(note or "")[:500],
                      paid_at=_when(paid_at), created_by=user_id)
    db.add(p)
    audit(db, user_id, "team_payment", "worker", worker.id, f"{worker.name} {kind} {total}")
    db.commit()
    out = summary(db, worker)
    out["ajoute"] = {"id": p.id, "type": kind, "montant": total}
    if out["reste_du"] < 0:
        out["attention"] = f"{worker.name} a reçu {-out['reste_du']:,.0f} de plus que le travail noté (avance à récupérer).".replace(",", " ")
    return out


def cancel(db: Session, entry_id: str, user_id: str | None = None) -> dict:
    """Erreur de saisie (travail ou paiement) : annulée, gardée au journal ; la dépense du chantier liée est annulée aussi."""
    row = db.get(WorkEntry, entry_id) or db.get(WorkerPayment, entry_id)
    if row is None:
        raise TeamError("Ligne introuvable.")
    row.status = "cancelled"
    if isinstance(row, WorkEntry) and row.expense_id:
        e = db.get(Expense, row.expense_id)
        if e is not None:
            e.status = "cancelled"
    audit(db, user_id, "team_cancel", "worker", row.worker_id, f"{type(row).__name__} {row.amount}")
    db.commit()
    return summary(db, db.get(Worker, row.worker_id))


def summary(db: Session, worker: Worker) -> dict:
    """Travail noté, avances, paies, reste dû ; et l'historique (le plus récent d'abord)."""
    work = db.query(WorkEntry).filter(WorkEntry.worker_id == worker.id).order_by(WorkEntry.day.desc(), WorkEntry.created_at.desc()).all()
    pays = db.query(WorkerPayment).filter(WorkerPayment.worker_id == worker.id).order_by(WorkerPayment.paid_at.desc()).all()
    live_w = [w for w in work if w.status != "cancelled"]
    live_p = [p for p in pays if p.status != "cancelled"]
    earned = round(sum(w.amount for w in live_w), 2)
    advances = round(sum(p.amount for p in live_p if p.kind == "avance"), 2)
    paid = round(sum(p.amount for p in live_p if p.kind == "paie"), 2)
    numbers = {q.id: q.number for q in db.query(Quotation).filter(Quotation.id.in_([w.quotation_id for w in work if w.quotation_id])).all()} \
        if any(w.quotation_id for w in work) else {}
    return {"id": worker.id, "nom": worker.name, "role": worker.role, "telephone": worker.phone, "mode": worker.pay_mode,
            "tarif_jour": worker.day_rate, "journees": round(sum(w.units for w in live_w if w.kind == "jour"), 2),
            "travail": earned, "avances": advances, "paye": paid, "reste_du": round(earned - advances - paid, 2),
            "historique": sorted(
                [{"id": w.id, "sorte": "travail", "date": w.day.date().isoformat() if w.day else None, "libelle": w.label,
                  "montant": w.amount, "chantier": numbers.get(w.quotation_id), "annule": w.status == "cancelled"} for w in work]
                + [{"id": p.id, "sorte": p.kind, "date": p.paid_at.date().isoformat() if p.paid_at else None,
                    "libelle": p.method or p.note, "montant": p.amount, "chantier": None, "annule": p.status == "cancelled"} for p in pays],
                key=lambda r: r["date"] or "", reverse=True)}


def overview(db: Session) -> dict:
    rows = [summary(db, w) for w in db.query(Worker).filter(Worker.active.is_(True)).order_by(Worker.name).all()]
    for r in rows:
        r.pop("historique", None)
    return {"ouvriers": rows, "reste_du_total": round(sum(r["reste_du"] for r in rows if r["reste_du"] > 0), 2)}
