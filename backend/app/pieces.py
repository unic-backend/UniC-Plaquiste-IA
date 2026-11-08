"""Calcul par pièce SANS l'IA : le patron saisit ses pièces (faux plafond, cloison, peinture), le moteur de calcul (calc.py, ses
règles) compte le matériel, sa grille de prix chiffre, et le devis se crée avec le même code que celui de l'IA. Aucun appel payant :
marche même quand l'API Claude est coupée.

Les pièces de même nature et mêmes options sont calculées ensemble (plafond : zones ; cloison : murs), comme le fait l'IA :
la marge et les paquets comptent une fois par groupe, pas une fois par pièce."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from app import calc

KINDS = {"ceiling": "Faux plafond", "partition": "Cloison", "paint": "Peinture"}
MAX_ROOMS = 40
DOOR = (0.9, 2.04)      # taille standard d'une porte (signalée « supposée » par le moteur)
WINDOW = (1.2, 1.2)
LABOUR_LINE = "Main-d'œuvre — pose complète"


def _num(room: dict, key: str, label: str, *, required: bool = True, lo: float = 0.01, hi: float = 500.0) -> float | None:
    v = room.get(key)
    if v in (None, ""):
        if required:
            raise ValueError(f"{label} manquante pour « {room['_label']} ».")
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} illisible pour « {room['_label']} ».") from None
    if not math.isfinite(f) or not lo <= f <= hi:
        raise ValueError(f"{label} hors limites pour « {room['_label']} » ({f:g}).")
    return f


def _clean(rooms: list[dict]) -> list[dict]:
    if not rooms:
        raise ValueError("Ajoute au moins une pièce.")
    if len(rooms) > MAX_ROOMS:
        raise ValueError(f"{MAX_ROOMS} pièces au plus par calcul.")
    out = []
    for i, raw in enumerate(rooms, 1):
        r = dict(raw or {})
        kind = r.get("kind")
        if kind not in KINDS:
            raise ValueError(f"Pièce {i} : type inconnu (faux plafond, cloison ou peinture).")
        r["_label"] = str(r.get("name") or "").strip()[:40] or f"{KINDS[kind]} {i}"
        if kind == "ceiling":
            r["length_m"], r["width_m"] = _num(r, "length_m", "Longueur"), _num(r, "width_m", "Largeur")
            r["suspente_m"] = _num(r, "suspente_m", "Hauteur de suspente", required=False, hi=30)
            r["support"] = "ipn" if r.get("support") == "ipn" else "dalle"
        elif kind == "partition":
            r["length_m"], r["height_m"] = _num(r, "length_m", "Longueur"), _num(r, "height_m", "Hauteur", hi=30)
            r["sides"] = 1 if int(r.get("sides") or 2) == 1 else 2
            r["doors"], r["windows"] = max(0, min(20, int(r.get("doors") or 0))), max(0, min(20, int(r.get("windows") or 0)))
        else:
            r["area_m2"] = _num(r, "area_m2", "Surface", hi=20000)
            r["coats"] = max(1, min(4, int(r.get("coats") or 2)))
        out.append(r)
    return out


def _cfg(db: Session, entraxe_cm: int | None) -> dict:
    from app.services import calc_fixings, company_dict
    co = company_dict(db)
    return {"waste": co.get("default_waste") or 0.0, "board_width": co.get("board_width_m") or 1.2,
            "board_height": co.get("board_height_m") or 2.0, "stud_spacing": (entraxe_cm / 100) if entraxe_cm in (50, 60) else (co.get("stud_spacing_m") or 0.6),
            "fixings": calc_fixings(co), "entraxe": entraxe_cm if entraxe_cm in (50, 60) else None}


def _ceiling(group: list[dict], cfg: dict) -> calc.CalcResult:
    zones = [(r["length_m"], r["width_m"]) for r in group]
    res = calc.calculate_ceiling(zones[0][0], zones[0][1], zones=zones, waste=cfg["waste"], board_width=cfg["board_width"],
                                 board_height=cfg["board_height"], fixing_values=cfg["fixings"], dims_known=True, entraxe_cm=cfg["entraxe"])
    tour = sum(2 * (r["length_m"] + r["width_m"]) for r in group if r.get("moulure"))
    if tour:
        calc.add_moulure(res, tour)
    if group[0].get("hydrofuge"):
        calc.make_hydrofuge(res, "Plaques hydrofuges (pièce humide cochée).")
    if group[0]["support"] == "ipn" or (group[0]["suspente_m"] or 0) > calc.ROD_M:
        calc.hang_from(res, group[0]["support"], group[0]["suspente_m"])
    return res   # vis et bande : arrondies au paquet / rouleau une seule fois sur tout le chantier (calculate)


def _partition(group: list[dict], cfg: dict) -> calc.CalcResult:
    walls = [(r["length_m"], r["height_m"]) for r in group]
    ops = []
    doors, windows = sum(r["doors"] for r in group), sum(r["windows"] for r in group)
    if doors:
        ops.append(calc.Opening("door", *DOOR, doors, assumed_size=True))
    if windows:
        ops.append(calc.Opening("window", *WINDOW, windows, assumed_size=True))
    res = calc.calculate_partition(walls[0][0], walls[0][1], group[0]["sides"], ops, walls=walls, waste=cfg["waste"],
                                   board_width=cfg["board_width"], board_height=cfg["board_height"], stud_spacing=cfg["stud_spacing"],
                                   fixing_values=cfg["fixings"], sides_known=True, openings_known=True)
    if group[0].get("hydrofuge"):
        calc.make_hydrofuge(res, "Plaques hydrofuges (pièce humide cochée).")
    return res   # vis et bande : arrondies au paquet / rouleau une seule fois sur tout le chantier (calculate)


def _groups(rooms: list[dict]) -> list[tuple[str, list[dict]]]:
    """Pièces calculées ensemble : même nature et mêmes options (plaques, accroche, faces) ; peinture : chaque pièce à part."""
    keyed: dict[tuple, list[dict]] = {}
    for r in rooms:
        if r["kind"] == "ceiling":
            key = ("ceiling", bool(r.get("hydrofuge")), r["support"], r["suspente_m"] or 0)
        elif r["kind"] == "partition":
            key = ("partition", bool(r.get("hydrofuge")), r["sides"])
        else:
            key = ("paint", id(r))
        keyed.setdefault(key, []).append(r)
    return [(k[0], g) for k, g in keyed.items()]


def calculate(db: Session, rooms: list[dict], entraxe_cm: int | None = None, labour_m2: float | None = None) -> dict[str, Any]:
    """Matériel et prix de toutes les pièces. `labour_m2` : prix de pose au m² donné par le patron (aucun prix n'est inventé)."""
    from app.services import material_by_sku, selling_price_for_sku
    rooms, cfg = _clean(rooms), _cfg(db, entraxe_cm)
    blocks, merged, ok = [], {}, True
    surface = 0.0
    for kind, group in _groups(rooms):
        try:
            res = (_ceiling(group, cfg) if kind == "ceiling" else _partition(group, cfg) if kind == "partition"
                   else calc.calculate_paint(group[0]["area_m2"], coats=group[0]["coats"]))
        except ValueError as exc:
            raise ValueError(f"{', '.join(r['_label'] for r in group)} : {exc}") from None
        data = res.to_dict()
        check = data.get("verification") or {"ok": True}
        ok = ok and bool(check.get("ok", True))
        names = ", ".join(r["_label"] for r in group)
        area = sum(r["length_m"] * r["width_m"] for r in group) if kind == "ceiling" else \
            sum(r["length_m"] * r["height_m"] * r["sides"] for r in group) if kind == "partition" else group[0]["area_m2"]
        if kind == "ceiling":
            surface += area
        elif kind == "partition":   # pose d'une cloison : au m² de mur (longueur × hauteur), faces comprises
            surface += sum(r["length_m"] * r["height_m"] for r in group)
        blocks.append({"pieces": names, "type": KINDS[kind], "surface_m2": round(area, 2), "titre": data.get("title"),
                       "quantites": data.get("quantities", []), "hypotheses": data.get("assumptions", []), "verification": check})
        for q in data.get("quantities", []):
            key = (q.get("sku") or q.get("name"), q.get("unit"))
            line = merged.setdefault(key, {"sku": q.get("sku") or "", "name": q.get("name"), "unit": q.get("unit"), "quantity": 0,
                                           "status": q.get("status"), "formula": []})
            line["quantity"] = round(line["quantity"] + float(q.get("quantity") or 0), 2)
            line["formula"].append(f"{names} : {q.get('formula') or ''}".strip(" :"))
    for key, line in list(merged.items()):   # vis au paquet de 1 000, bande au rouleau de 150 m : une seule fois pour tout le chantier
        if line["sku"] in ("VIS-PLAQUE", "BANDE-JOINT"):
            pack = (calc.screw_pack_line(int(line["quantity"]), "toutes les pièces") if line["sku"] == "VIS-PLAQUE"
                    else calc.tape_roll_line(float(line["quantity"]), "toutes les pièces"))
            merged[key] = {**line, "sku": pack.sku, "name": pack.name, "unit": pack.unit, "quantity": pack.quantity, "status": pack.status,
                           "formula": [pack.formula, *line["formula"]]}
    lines, total, missing = [], 0.0, []
    for line in merged.values():
        price = selling_price_for_sku(db, line["sku"])[0] if line["sku"] and material_by_sku(db, line["sku"]) else None
        amount = round(line["quantity"] * price) if price is not None else None
        if amount is None:
            missing.append(line["name"])
        else:
            total += amount
        lines.append({**line, "formula": " | ".join(line["formula"]), "prix_unitaire": price, "montant": amount})
    labour = None
    if labour_m2 is not None:
        if not math.isfinite(labour_m2) or labour_m2 < 0:
            raise ValueError("Prix de pose au m² invalide.")
        labour = {"name": LABOUR_LINE, "unit": "m²", "quantity": round(surface, 2), "prix_unitaire": labour_m2,
                  "montant": round(surface * labour_m2), "status": "confirmed", "sku": "",
                  "formula": "surface posée (plafonds au m², cloisons au m² de mur) × prix au m²"}
        total += labour["montant"]
    return {"blocs": blocks, "lignes": lines, "main_oeuvre": labour, "surface_posee_m2": round(surface, 2), "total": round(total),
            "prix_manquants": missing, "complet": not missing, "ok": ok,
            "note": "Calcul fait par le moteur UniC (règles du patron), sans l'IA : aucun appel payant."}


def objet_auto(rooms: list[dict]) -> str:
    """Objet du devis écrit à partir des pièces : « Fourniture : faux plafond BA13 salon (5 × 4 m) ; cloison couloir (3 × 2,6 m, 2 faces). »"""
    n = lambda x: f"{x:g}".replace(".", ",")   # noqa: E731
    parts = []
    for r in _clean(rooms):
        if r["kind"] == "ceiling":
            parts.append(f"faux plafond BA13 {r['_label'].lower()} ({n(r['length_m'])} × {n(r['width_m'])} m)")
        elif r["kind"] == "partition":
            parts.append(f"cloison {r['_label'].lower()} ({n(r['length_m'])} × {n(r['height_m'])} m, {r['sides']} face{'s' if r['sides'] > 1 else ''})")
        else:
            parts.append(f"peinture {r['_label'].lower()} ({n(r['area_m2'])} m²)")
    return "Fourniture : " + " ; ".join(parts) + "."


def create_quote(db: Session, user_id: str | None, rooms: list[dict], *, client: str, lieu: str = "", objet: str = "",
                 entraxe_cm: int | None = None, labour_m2: float | None = None):
    """Devis du calcul par pièce : même création que l'IA (numéro, prix de la grille, livraison, PDF). Jamais sur un calcul en écart."""
    from app import services
    if not (client or "").strip():
        raise ValueError("Nom du client requis pour le devis.")
    res = calculate(db, rooms, entraxe_cm, labour_m2)
    if not res["ok"]:
        raise ValueError("Le contrôle indépendant du calcul a trouvé un écart : aucun devis n'est créé.")
    quantities = [{"sku": l["sku"], "name": l["name"], "quantity": l["quantity"], "unit": l["unit"], "status": l["status"] or "estimated",
                   "formula": l["formula"]} for l in res["lignes"]]
    if res["main_oeuvre"]:
        mo = res["main_oeuvre"]
        quantities.append({"name": mo["name"], "quantity": mo["quantity"], "unit": "m²", "status": "confirmed", "fixed_price": mo["prix_unitaire"],
                           "formula": mo["formula"]})
    hyps = [h for b in res["blocs"] for h in b["hypotheses"]]
    return services.quotation_from_quantities(db, title="", quantities=quantities, customer_id=None, project_id=None, user_id=user_id,
                                              client_name=client.strip(), objet=(objet or "").strip() or objet_auto(rooms), lieu=lieu.strip(),
                                              assumptions=hyps)
