"""Preuves d'un devis : POURQUOI ce montant, des semaines ou des mois plus tard.

À la création d'un devis, on garde une trace figée : d'où viennent les chiffres (calcul du moteur ou lignes données par le patron),
les mesures d'origine avec leur unité, chaque étape (formule, valeurs, résultat, statut), les hypothèses et les manques, le contrôle
indépendant, la version du moteur, la date, et le prix utilisé pour chaque ligne (grille UniC, date de saisie). Lecture seule ensuite :
une correction du devis ne réécrit jamais cette trace (on la compare à la version actuelle).

Statuts : confirmed (mesure confirmée), calculated (formule appliquée à des mesures confirmées), estimated (calcul avec hypothèses),
assumed (hypothèse provisoire), missing (absent), conflicting (sources contradictoires).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import calc
from app.models import Material, Quotation

STATUS_FR = {"confirmed": "confirmé", "calculated": "calculé", "estimated": "estimé", "assumed": "supposé",
             "missing": "manquant", "conflicting": "contradictoire"}
MAX_STEPS = 40


def _price_proof(db: Session, item) -> dict:
    """Prix de vente retenu pour une ligne : la ligne elle-même + la fiche de prix de la grille à cet instant (id, date, source)."""
    out: dict[str, Any] = {"ligne": item.description, "quantite": item.quantity, "unite": item.unit, "prix_unitaire": item.unit_price,
                           "total": item.total, "statut": item.data_status, "formule": item.formula or ""}
    if item.material_id and item.unit_price is not None:
        from app.services import current_price
        mat = db.get(Material, item.material_id)
        cur = current_price(db, item.material_id, "selling") if mat is not None else None
        if cur is not None and abs(cur.amount - item.unit_price) < 0.005:
            out["prix_source"] = f"grille UniC ({mat.sku})"
            out["prix_saisi_le"] = cur.valid_from.date().isoformat() if cur.valid_from else None
            out["prix_ref"] = cur.id
    elif item.unit_price is None:
        out["prix_source"] = "prix non renseigné : ligne laissée vide, rien d'inventé"
    return out


def build_trace(db: Session, quote: Quotation, calc_data: dict | None, *, owner_request: str = "") -> dict:
    """Trace d'origine d'un devis tout juste créé. `calc_data` = résultat du moteur (CalcResult.to_dict()) ou None (lignes du patron)."""
    now = datetime.now(timezone.utc).isoformat()
    trace: dict[str, Any] = {
        "version_trace": 1, "cree_le": now, "devis": quote.number, "version_devis": quote.version or 1,
        "demande": (owner_request or "")[:400],
        "source": "calcul du moteur UniC" if calc_data else "lignes données telles quelles par le patron (aucun calcul de quantités)",
        "lignes": [_price_proof(db, it) for it in quote.items],
        "totaux": {"sous_total": quote.subtotal, "tva_taux": quote.vat_rate, "tva": quote.vat_amount, "total": quote.total,
                   "devise": quote.currency},
    }
    if calc_data:
        trace.update({
            "moteur": {"version": calc_data.get("engine_version") or calc.ENGINE_VERSION, "type": calc_data.get("kind"),
                       "titre": calc_data.get("title")},
            "comprehension": calc_data.get("understanding"),
            "mesures": calc_data.get("data_used") or [],
            "entrees": calc_data.get("inputs") or {},
            "etapes": [{"etape": st.get("label"), "formule": st.get("formula"), "valeurs": st.get("inputs"), "resultat": st.get("result"),
                        "unite": st.get("unit"), "statut": st.get("status")} for st in (calc_data.get("steps") or [])[:MAX_STEPS]],
            "hypotheses": calc_data.get("assumptions") or [],
            "manquant": calc_data.get("missing") or [],
            "controle_independant": calc_data.get("verification"),
        })
    return trace


def save(quote: Quotation, trace: dict) -> None:
    quote.calc_trace = json.dumps(trace, ensure_ascii=False, default=str)


def load(quote: Quotation) -> dict | None:
    try:
        return json.loads(quote.calc_trace) if quote.calc_trace else None
    except ValueError:
        return None


def explain(quote: Quotation) -> dict:
    """« Pourquoi ce montant ? » : explication lisible, fabriquée par le code à partir de la trace figée (aucune IA, rien d'inventé)."""
    t = load(quote)
    if t is None:
        return {"disponible": False, "resume": ("Aucune trace d'origine pour ce devis (créé avant la mise en place des preuves, ou saisi à la main). "
                                                 "Les lignes, quantités et prix du devis restent consultables."),
                "version_devis": quote.version or 1}
    lines: list[str] = []
    when = (t.get("cree_le") or "")[:10]
    lines.append(f"Devis {t.get('devis')} créé le {when} — {t.get('source')}.")
    if t.get("demande"):
        lines.append(f"Demande du patron : « {t['demande'][:200]} »")
    if t.get("moteur"):
        lines.append(f"Moteur de calcul version {t['moteur'].get('version')} ({t['moteur'].get('titre') or t['moteur'].get('type')}).")
    if t.get("comprehension"):
        lines.append("Compris : " + str(t["comprehension"]))
    for m in t.get("mesures") or []:
        lines.append(f"• {m.get('label')} : {m.get('value')} {m.get('unit') or ''} [{STATUS_FR.get(m.get('status'), m.get('status'))}]".replace("  ", " "))
    for st in t.get("etapes") or []:
        lines.append(f"→ {st['etape']} = {st['resultat']} {st.get('unite') or ''} ({st.get('formule')}) "
                     f"[{STATUS_FR.get(st.get('statut'), st.get('statut'))}]".replace("  ", " "))
    for h in t.get("hypotheses") or []:
        lines.append(f"Hypothèse : {h}")
    for m in t.get("manquant") or []:
        lines.append(f"Manquait : {m}")
    check = t.get("controle_independant")
    if check:
        lines.append("Contrôle indépendant : " + ("recalcul concordant ✓" if check.get("ok") else "ÉCART : " + "; ".join(check.get("problems") or [])))
    now_lines = [(it.description, it.quantity, it.unit_price) for it in quote.items]
    for l in t.get("lignes") or []:
        src = f" — {l['prix_source']}" + (f" (prix saisi le {l['prix_saisi_le']})" if l.get("prix_saisi_le") else "") if l.get("prix_source") else ""
        unit_price = l.get("prix_unitaire")
        price_txt = "prix non renseigné" if unit_price is None else f"{unit_price:g}"
        lines.append(f"Ligne : {l['ligne']} — {l['quantite']:g} {l.get('unite') or ''} × {price_txt}{src}".replace("  ", " "))
    tot = t.get("totaux") or {}
    lines.append(f"Total d'origine : {tot.get('total')} {tot.get('devise') or ''}.".replace("  ", " "))
    changed = (quote.version or 1) != (t.get("version_devis") or 1)
    if changed:
        lines.append(f"⚠️ Le devis est maintenant en version {quote.version} (trace faite en version {t.get('version_devis')}) : les lignes ont pu être "
                     f"corrigées depuis ; total actuel {quote.total}. Cette trace décrit le calcul d'ORIGINE.")
    return {"disponible": True, "resume": "\n".join(lines), "trace": t, "modifie_depuis": changed, "version_devis": quote.version or 1,
            "lignes_actuelles": now_lines}


def price_changed_since(db: Session, quote: Quotation) -> list[dict]:
    """Lignes dont le prix de la grille a changé depuis la création du devis (info pour le patron, rien n'est modifié)."""
    from app.services import current_price
    out = []
    for it in quote.items:
        if not it.material_id or it.unit_price is None:
            continue
        cur = current_price(db, it.material_id, "selling")
        if cur is not None and abs(cur.amount - it.unit_price) >= 0.005:
            out.append({"ligne": it.description, "prix_du_devis": it.unit_price, "prix_actuel_grille": cur.amount})
    return out


__all__ = ["build_trace", "save", "load", "explain", "price_changed_since"]
