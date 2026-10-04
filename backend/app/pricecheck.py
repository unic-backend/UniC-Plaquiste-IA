"""Contrôle des prix : une consigne n'est pas une garantie. Ce module LIT ce qui a été écrit et le compare à la grille.

Il ne corrige rien : c'est le document et le tarif du patron. Il signale, avec la ligne fautive.
- check_quote : chaque ligne d'un devis contre le prix de vente enregistré + cohérence des totaux ;
- review_reply : une réponse de l'IA qui cite un article de la grille avec un autre prix.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session, object_session

from app.models import Material, Quotation
from app.services import current_price

_SEPARATORS = "    ."
_AMOUNT = re.compile(rf"\b\d{{1,3}}(?:[{re.escape(_SEPARATORS)}]\d{{3}})+\b|\b\d{{3,}}\b")
MIN_AMOUNT = 100
TOLERANCE = 0.011


def _amounts(line: str) -> list[int]:
    out = []
    for raw in _AMOUNT.findall(line):
        try:
            v = int(re.sub(f"[{re.escape(_SEPARATORS)}]", "", raw))
        except ValueError:
            continue
        if v >= MIN_AMOUNT:
            out.append(v)
    return out


def check_quote(q: Quotation) -> list[dict]:
    """Anomalies d'un devis. Liste vide = prix conformes à la grille et totaux cohérents."""
    db = object_session(q)
    issues: list[dict] = []
    subtotal = 0.0
    priced = 0
    for it in sorted(q.items, key=lambda x: x.position):
        if it.unit_price is None:
            continue
        priced += 1
        if db is not None and it.material_id:
            price = current_price(db, it.material_id, "selling")
            if price is not None and abs(price.amount - it.unit_price) > TOLERANCE:
                issues.append({"type": "prix", "ligne": it.description, "attendu": price.amount, "trouve": it.unit_price})
        expected = round(it.quantity * it.unit_price, 2)
        if it.total is None or abs(it.total - expected) > TOLERANCE:
            issues.append({"type": "total_ligne", "ligne": it.description, "attendu": expected, "trouve": it.total})
        subtotal += it.total or 0.0
    if priced and q.subtotal is not None and abs(q.subtotal - round(subtotal, 2)) > TOLERANCE:
        issues.append({"type": "sous_total", "ligne": "Sous-total", "attendu": round(subtotal, 2), "trouve": q.subtotal})
    if q.subtotal is not None and q.vat_rate is not None and q.total is not None:
        expected_total = round(q.subtotal * (1 + q.vat_rate), 2)
        if abs(q.total - expected_total) > TOLERANCE:
            issues.append({"type": "total", "ligne": "Total", "attendu": expected_total, "trouve": q.total})
    return issues


def review_reply(db: Session, reply: str) -> str:
    """Avertissement à ajouter si la réponse cite un article de la grille avec un montant qui n'en est pas un multiple."""
    if not reply:
        return ""
    grid: dict[str, float] = {}
    for m in db.query(Material).filter(Material.is_active.is_(True)).all():
        p = current_price(db, m.id, "selling")
        if p is not None and p.amount and float(p.amount).is_integer():
            grid[m.name.lower()] = int(p.amount)
    if not grid:
        return ""
    found: list[str] = []
    for line in reply.splitlines():
        amounts = _amounts(line)
        if not amounts:
            continue
        low = line.lower()
        for name, price in grid.items():
            if name in low and not any(a % price == 0 for a in amounts):
                found.append(f"{name} : {price} attendu — « {line.strip()[:90]} »")
    if not found:
        return ""
    return ("\n\n---\n⚠️ **Prix à vérifier avant d'utiliser cette réponse.** Ces articles figurent dans ta grille avec un autre prix :\n\n"
            + "\n".join(f"- {f}" for f in found[:6]) + "\n\nJe ne corrige pas moi-même : c'est ton tarif.")
