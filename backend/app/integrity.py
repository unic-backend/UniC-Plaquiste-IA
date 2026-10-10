"""Surveillance de la COHÉRENCE : ce que la santé technique (selfcare) ne voit pas.

Détecte seulement, jamais de correction automatique : un document dont les chiffres ne tombent pas juste est signalé au patron,
avec la raison, et il décide. Contrôles déterministes (code, pas un modèle), lecture seule.

- Documents : total de devis ≠ somme des lignes ; TVA incohérente ; facture « payé + reste ≠ total » ; payé ≠ somme des versements ;
  PDF enregistré mais fichier absent du disque ; montants négatifs ; numéros dupliqués.
- Serveur : taux d'erreurs 5xx et lenteur sur les dernières requêtes (compteur en mémoire, alimenté par main.py).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

TOLERANCE = 1.01   # écart toléré (arrondis en FCFA)
MAX_LISTED = 8
_REQUESTS: deque = deque(maxlen=500)   # (statut, durée ms) des dernières requêtes /api
SLOW_MS = 4000
ERROR_RATE_ALERT = 0.05   # plus de 5 % d'erreurs serveur sur les dernières requêtes


def record_request(status: int, ms: float) -> None:
    _REQUESTS.append((int(status), float(ms)))


def reset_requests() -> None:
    _REQUESTS.clear()


def _issue(kind: str, ref: str, detail: str) -> dict:
    return {"kind": kind, "ref": ref, "detail": detail}


def _documents(db: Session) -> list[dict]:
    from app.models import Artifact, Invoice, Payment, Quotation, QuotationItem
    out: list[dict] = []
    sums = dict(db.query(QuotationItem.quotation_id, func.sum(QuotationItem.total)).group_by(QuotationItem.quotation_id).all())
    for q in db.query(Quotation).filter(Quotation.status != "cancelled").all():
        if q.subtotal is not None and q.subtotal < 0 or (q.total is not None and q.total < 0):
            out.append(_issue("montant négatif", q.number, "devis avec un montant négatif"))
            continue
        lines = sums.get(q.id)
        if q.subtotal is not None and lines is not None and abs(q.subtotal - lines) > TOLERANCE:
            out.append(_issue("devis", q.number, f"sous-total {q.subtotal:,.0f} ≠ somme des lignes {lines:,.0f}".replace(",", " ")))
        if q.subtotal is not None and q.total is not None:
            expected = q.subtotal + (q.vat_amount or 0)
            if abs(q.total - expected) > TOLERANCE:
                out.append(_issue("devis", q.number, f"total {q.total:,.0f} ≠ sous-total + TVA {expected:,.0f}".replace(",", " ")))
        if q.vat_rate is not None and q.vat_amount is not None and q.subtotal is not None \
                and abs(q.subtotal * q.vat_rate - q.vat_amount) > TOLERANCE:
            out.append(_issue("devis", q.number, "TVA différente de sous-total × taux"))
    paid_by_invoice = dict(db.query(Payment.invoice_id, func.sum(Payment.amount)).group_by(Payment.invoice_id).all())
    for i in db.query(Invoice).filter(Invoice.status != "cancelled", Invoice.kind != "credit").all():
        got = paid_by_invoice.get(i.id, 0) or 0
        if i.total is not None:
            if abs((i.paid or 0) - got) > TOLERANCE:
                out.append(_issue("facture", i.number, f"payé {i.paid or 0:,.0f} ≠ somme des versements {got:,.0f}".replace(",", " ")))
            elif i.remaining is not None and abs(i.total - (i.paid or 0) - i.remaining) > TOLERANCE:
                out.append(_issue("facture", i.number, "payé + reste ≠ total"))
        if (i.paid or 0) < 0:
            out.append(_issue("montant négatif", i.number, "facture avec un montant payé négatif"))
    for a in db.query(Artifact).filter(Artifact.status == "ready").all():
        if a.path and not Path(a.path).exists():
            out.append(_issue("fichier", a.filename, "PDF enregistré mais absent du disque (il sera recréé à la prochaine ouverture)"))
    for model, label in ((Quotation, "devis"), (Invoice, "facture")):
        dup = db.query(model.number).group_by(model.number).having(func.count() > 1).all()
        out += [_issue("numéro dupliqué", n, f"deux {label}s portent ce numéro") for (n,) in dup]
    return out


def _server() -> list[dict]:
    recent = list(_REQUESTS)
    out: list[dict] = []
    if len(recent) >= 20:
        errors = sum(1 for s, _ in recent if s >= 500)
        if errors / len(recent) > ERROR_RATE_ALERT:
            out.append(_issue("serveur", "erreurs", f"{errors} erreurs serveur sur les {len(recent)} dernières requêtes"))
        slow = sorted(ms for _, ms in recent)[int(len(recent) * 0.95) - 1]
        if slow > SLOW_MS:
            out.append(_issue("serveur", "lenteur", f"5 % des requêtes dépassent {slow / 1000:.1f} s"))
    return out


def check(db: Session) -> dict[str, Any]:
    """Rapport de cohérence : {ok, problems:[{kind, ref, detail}], total, requests}. Lecture seule."""
    problems = _documents(db) + _server()
    return {"ok": not problems, "total": len(problems), "problems": problems[:MAX_LISTED * 3],
            "requests": len(_REQUESTS), "note": "Détection seulement : rien n'est corrigé tout seul. Dis-moi lequel corriger."}


def summary(db: Session) -> str:
    """Une ligne pour le briefing (vide si tout est cohérent)."""
    r = check(db)
    if r["ok"]:
        return ""
    head = "; ".join(f"{p['ref']} ({p['detail']})" for p in r["problems"][:3])
    return f"{r['total']} incohérence(s) : {head}"

