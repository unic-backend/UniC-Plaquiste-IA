"""Du plan au devis : les pièces lues sur le plan deviennent un métré, sans rien redemander au patron.

Plafonds : plaques calculées sur la surface TOTALE de chaque type (standard / hydrofuge) pour ne pas arrondir pièce par
pièce ; ossature et suspentes calculées pièce par pièce (elles dépendent des dimensions). Cloisons : longueur × hauteur.
Chaque pièce retenue, sa surface et sa source (plan) sont écrites dans les hypothèses du devis : tout est traçable.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict

from app import calc


class PlanQuoteError(Exception):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def _match(name: str, wanted: list[str]) -> bool:
    n = _norm(name)
    return any(w and (_norm(w) == n or _norm(w) in n or n in _norm(w)) for w in wanted)


def build(analysis: dict, *, rooms: list[str] | None = None, include_to_confirm: bool = False,
          hydrofuge_rooms: list[str] | None = None, partitions: list[dict] | None = None,
          waste: float = 0.08, board_width: float = 1.2, board_length: float = 2.0, stud_spacing: float = 0.6) -> dict:
    """Métré (format de CalcResult.to_dict) à partir de l'analyse du plan."""
    pieces = analysis.get("pieces") or []
    if not pieces and not partitions:
        raise PlanQuoteError("Aucune pièce lue sur ce plan : relis le plan (read_plan) ou donne les dimensions.")
    hydro = hydrofuge_rooms or []
    if rooms:
        chosen = [p for p in pieces if _match(p["nom"], rooms)]
        unknown = [r for r in rooms if not any(_match(p["nom"], [r]) for p in pieces)]
        if unknown:
            raise PlanQuoteError(f"Pièce(s) absente(s) du plan : {', '.join(unknown)}. Pièces lues : "
                                 + ", ".join(p["nom"] for p in pieces))
    else:
        flags = {"oui", "a_confirmer"} if include_to_confirm else {"oui"}
        chosen = [p for p in pieces if p.get("plafond") in flags]
        if pieces and not chosen and not partitions:
            raise PlanQuoteError("Le plan ne confirme aucun plafond : demande au patron quelles pièces ont un faux plafond "
                                 "(ou include_to_confirm=true s'il dit « toutes »).")

    steps, assumptions, missing = [], [], []
    others: dict[str, dict] = {}
    area_by_type = {"": 0.0, "-H": 0.0}

    def add(line: calc.QuantityLine) -> None:
        cur = others.get(line.sku)
        if cur is None:
            others[line.sku] = asdict(line)
        else:
            cur["quantity"] = calc.round_qty(cur["quantity"] + line.quantity, 2)

    for p in chosen:
        area = p.get("surface_m2")
        if not area:
            missing.append(f"{p['nom']} : surface non lisible sur le plan, non comptée.")
            continue
        L, l = p.get("longueur_m"), p.get("largeur_m")
        if not (L and l):
            L = l = math.sqrt(area)
            assumptions.append(f"{p['nom']} : dimensions non cotées, ossature estimée sur un carré de {area:g} m².")
        suffix = "-H" if _match(p["nom"], hydro) else ""
        area_by_type[suffix] += area
        res = calc.calculate_ceiling(L, l, waste=waste, board_width=board_width, board_height=board_length)
        for q in res.quantities:
            if not q.sku.startswith("BA13-"):   # plaques comptées plus bas, sur le total
                add(q)
        steps.append(calc.CalcStep(f"Plafond {p['nom']}" + (" (hydrofuge)" if suffix else ""), "surface lue sur le plan",
                                   {"page": p.get("page") or 1}, area, "m²", calc.STATUS_CONFIRMED))
        assumptions.append(f"{p['nom']} : {area:g} m² (plan" + (", hydrofuge" if suffix else "") + ").")

    boards = []
    for suffix, total in area_by_type.items():
        if total <= 0:
            continue
        sku, name = calc.board_sku(board_width, board_length, suffix)
        if suffix:
            name = name.replace("BA13", "BA13 hydrofuge")
        n = calc.boards_needed(total, waste, calc.board_area(board_width, board_length))
        boards.append(asdict(calc.QuantityLine(sku, name, n, "u", f"⌈{total:g} × (1+{waste:g}) / {board_width * board_length:g}⌉",
                                               calc.STATUS_ESTIMATED)))
        steps.append(calc.CalcStep("Plaques " + ("hydrofuges" if suffix else "standard"), "⌈ S × (1+d) / Splaque ⌉",
                                   {"S": round(total, 2), "d": waste}, n, "u", calc.STATUS_ESTIMATED))

    for c in partitions or []:
        length, height = float(c.get("length_m") or 0), float(c.get("height_m") or 0)
        if length <= 0 or height <= 0:
            raise PlanQuoteError("Cloison : longueur et hauteur requises (la hauteur n'est pas sur le plan, demande-la).")
        sides = int(c.get("sides") or 2)
        res = calc.calculate_partition(length, height, sides, [], waste=waste, board_width=board_width,
                                       board_height=board_length, stud_spacing=stud_spacing)
        for q in res.quantities:
            add(q)
        label = c.get("label") or "Cloison"
        steps.append(calc.CalcStep(label, "longueur × hauteur", {"L": length, "h": height, "faces": sides},
                                   round(length * height, 2), "m²", calc.STATUS_CALCULATED))
        assumptions.append(f"{label} : {length:g} m × {height:g} m, {sides} face(s).")

    # plaques des cloisons fusionnées avec celles des plafonds de même référence
    quantities = boards[:]
    for sku, q in others.items():
        same = next((b for b in quantities if b["sku"] == sku), None)
        if same:
            same["quantity"] += q["quantity"]
        else:
            quantities.append(q)
    if not quantities:
        raise PlanQuoteError("Rien à chiffrer : aucune pièce avec surface ni cloison retenue.")

    check = analysis.get("controle_emprise") or {}
    if check.get("note"):
        assumptions.append(check["note"])
    total_ceiling = round(sum(area_by_type.values()), 2)
    title = f"Métré depuis le plan {analysis.get('fichier') or ''}".strip()
    return {
        "kind": "plan", "title": title,
        "understanding": f"{len([s for s in steps if s.label.startswith('Plafond')])} pièce(s) en faux plafond, "
                         f"{total_ceiling:g} m²" + (f", {len(partitions or [])} cloison(s)" if partitions else "") + ".",
        "steps": [asdict(s) for s in steps], "quantities": quantities,
        "assumptions": assumptions + [f"Déchet {waste * 100:.0f} %. Plaques {board_width:g} × {board_length:g} m."],
        "missing": missing, "notes": [], "data_used": [], "inputs": {"surface_plafond_m2": total_ceiling},
        "next_step": "Prêt pour le devis.",
    }
