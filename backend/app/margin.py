"""Marge d'un devis : prix de vente ligne par ligne contre le prix d'ACHAT enregistré par le patron.

Aucune donnée inventée : un prix d'achat absent reste « inconnu » (jamais un pourcentage supposé), la main-d'œuvre n'a pas de
coût d'achat en base (exclue), et le seuil de marge minimale vient du patron (réglage `min_margin_pct`) : sans seuil, seules les
ventes À PERTE (vente < achat) sont signalées. Réservé au patron : jamais dans un document client.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, object_session

from app.models import AppSetting, Material, Quotation
from app.services import current_price

SETTING_KEY = "min_margin_pct"


def get_min_margin(db: Session) -> float | None:
    row = db.get(AppSetting, SETTING_KEY)
    try:
        return float(row.value) if row and row.value not in ("", None) else None
    except ValueError:
        return None


def set_min_margin(db: Session, pct: float | None) -> float | None:
    if pct is not None and not 0 <= pct < 100:
        raise ValueError("La marge minimale doit être entre 0 % et 100 % (exclu).")
    row = db.get(AppSetting, SETTING_KEY)
    value = "" if pct is None else str(pct)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    db.flush()
    return pct


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def analyze(q: Quotation, min_margin_pct: float | None = None) -> dict:
    """Marge du devis. Marge = (vente − achat) / vente, sur les seules lignes dont le prix d'achat est connu."""
    db = object_session(q)
    lines, loss, low, unknown, labour = [], [], [], [], []
    sale_known = cost_known = sale_total = 0.0
    if min_margin_pct is None and db is not None:
        min_margin_pct = get_min_margin(db)
    for it in q.items:
        if it.unit_price is None or not it.quantity:
            continue   # ligne sans prix de vente : déjà signalée par le contrôle des prix
        sale = round(it.unit_price * it.quantity, 2)
        sale_total += sale
        mat = db.get(Material, it.material_id) if db is not None and it.material_id else None
        buy = current_price(db, mat.id, "purchase") if mat is not None and db is not None else None
        if mat is None:
            labour.append(it.description)   # pas un matériau du catalogue (main-d'œuvre, forfait…) : aucun coût d'achat en base
            continue
        if buy is None:
            unknown.append(it.description)
            continue
        cost = round(buy.amount * it.quantity, 2)
        margin = round(sale - cost, 2)
        sale_known += sale
        cost_known += cost
        row = {"ligne": it.description, "vente": sale, "achat": cost, "marge": margin, "marge_pct": _pct(margin, sale)}
        lines.append(row)
        if margin < 0:
            loss.append(row)
        elif min_margin_pct is not None and row["marge_pct"] is not None and row["marge_pct"] < min_margin_pct:
            low.append(row)
    covered = _pct(sale_known, sale_total)
    margin_known = round(sale_known - cost_known, 2)
    alerts: list[str] = []
    for r in loss:
        alerts.append(f"VENTE À PERTE : {r['ligne']} (vendu {r['vente']:,.0f}, acheté {r['achat']:,.0f})".replace(",", " "))
    for r in low:
        alerts.append(f"Marge basse : {r['ligne']} ({r['marge_pct']} % < seuil {min_margin_pct:g} %)")
    if unknown:
        alerts.append(f"Prix d'achat inconnu pour {len(unknown)} ligne(s) : marge non calculable ({', '.join(unknown[:4])}).")
    return {"numero": q.number, "ventes": round(sale_total, 2), "marge_connue": margin_known if lines else None,
            "marge_pct": _pct(margin_known, sale_known) if lines else None, "couverture_pct": covered,
            "seuil_pct": min_margin_pct, "a_perte": loss, "marge_basse": low, "achat_inconnu": unknown, "hors_catalogue": labour,
            "lignes": lines, "alertes": alerts,
            "ok": not loss and not low,
            "note": ("Marge calculée sur les lignes dont le prix d'achat est enregistré (" + (f"{covered} %" if covered is not None else "0 %")
                     + " des ventes). Main-d'œuvre et forfaits exclus. Pour le patron seulement : à ne jamais montrer au client.")}
