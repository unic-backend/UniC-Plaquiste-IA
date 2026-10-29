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
          waste: float = 0.0, board_width: float = 1.2, board_length: float = 2.0, stud_spacing: float = 0.6,
          fixings: dict | None = None) -> dict:
    """Métré (format de CalcResult.to_dict) à partir de l'analyse du plan. Chaque pièce est comptée juste (plaques au plan de
    pose) ; la marge du patron (en pièces) est ajoutée UNE fois par article du faux plafond, selon la surface de plafond qu'il
    couvre sur tout le plan (plaques hydrofuges : les pièces humides). Cloisons : aucune marge (règle du patron)."""
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
    boards_by_type = {"": 0, "-H": 0}   # plaques au plan de pose, pièce par pièce
    partition_m2 = 0.0
    fx = calc.fixings(fixings)
    # articles vendus au paquet : les pièces de TOUTES les pièces du plan sont additionnées, puis arrondies au paquet une seule
    # fois (sinon 5 pièces à 30 chevilles = 5 paquets au lieu de 2)
    pack = {"UC-PIVOT": 100, "UC-CHEVILLES-A-LETON": 100, "UC-PAQUET-CHEVILLES-A-FRAPPER": fx["anchors_per_pack"],
            "UC-VIS-9-MM": fx["screws9_per_pack"]}
    pieces: dict[str, int] = {}

    def count(sku: str, n: int) -> None:
        pieces[sku] = pieces.get(sku, 0) + int(n)

    def step_result(res, prefix: str) -> int:
        return int(next(st.result for st in res.steps if st.label.startswith(prefix)))

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
        res = calc.calculate_ceiling(L, l, waste=waste, board_width=board_width, board_height=board_length, fixing_values=fixings,
                                     margin=False)
        boards_by_type[suffix] += int(next(q.quantity for q in res.quantities if q.sku.startswith("BA13-")))
        hangers = step_result(res, "Points d'accroche")
        count("UC-PIVOT", hangers)
        count("UC-CHEVILLES-A-LETON", hangers)
        count("UC-PAQUET-CHEVILLES-A-FRAPPER", calc.anchor_points(2 * (L + l), 4, fx["anchor_spacing_m"]))
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
        n = boards_by_type[suffix]
        boards.append(asdict(calc.QuantityLine(sku, name, n, "u", f"plan de pose, pièce par pièce ({total:g} m²)".replace(".", ","),
                                               calc.STATUS_ESTIMATED)))
        steps.append(calc.CalcStep("Plaques " + ("hydrofuges" if suffix else "standard"),
                                   "Σ plan de pose des pièces : entières + morceaux comptés en plaques entières",
                                   {"S": round(total, 2)}, n, "u", calc.STATUS_ESTIMATED))

    for c in partitions or []:
        length, height = float(c.get("length_m") or 0), float(c.get("height_m") or 0)
        if length <= 0 or height <= 0:
            raise PlanQuoteError("Cloison : longueur et hauteur requises (la hauteur n'est pas sur le plan, demande-la).")
        sides = int(c.get("sides") or 2)
        res = calc.calculate_partition(length, height, sides, [], waste=waste, board_width=board_width,
                                       board_height=board_length, stud_spacing=stud_spacing, fixing_values=fixings)
        partition_m2 += length * height
        count("UC-PAQUET-CHEVILLES-A-FRAPPER", calc.anchor_points(2 * length, 2, fx["anchor_spacing_m"]))
        count("UC-VIS-9-MM", step_result(res, "Nombre de montants") * fx["screws9_per_stud"])
        for q in res.quantities:
            add(q)
        label = c.get("label") or "Cloison"
        steps.append(calc.CalcStep(label, "longueur × hauteur", {"L": length, "h": height, "faces": sides},
                                   round(length * height, 2), "m²", calc.STATUS_CALCULATED))
        assumptions.append(f"{label} : {length:g} m × {height:g} m, {sides} face(s).")

    for sku, n in pieces.items():   # paquets recalculés sur le total des pièces
        if sku in others:
            others[sku]["quantity"] = calc.ceil_int(n / pack[sku])
            others[sku]["formula"] = f"⌈ {n} pièces (toutes les pièces du plan) / {pack[sku]} ⌉"
    # plaques des cloisons fusionnées avec celles des plafonds de même référence
    quantities = boards[:]
    for sku, q in others.items():
        same = next((b for b in quantities if b["sku"] == sku), None)
        if same:
            same["quantity"] += q["quantity"]
            same["formula"] += f" + cloisons ({q['quantity']:g})"
        else:
            quantities.append(q)
    if not quantities:
        raise PlanQuoteError("Rien à chiffrer : aucune pièce avec surface ni cloison retenue.")
    # marge du patron : une fois par article du faux plafond, sur la surface de plafond qu'il couvre (cloisons : aucune)
    ceiling_m2 = round(sum(area_by_type.values()), 2)
    marges = {}
    for q in quantities:
        if calc.takes_margin(q["sku"]):
            surface = ceiling_m2 if q["sku"] in calc.MARGIN_SKUS else round(area_by_type["-H" if q["sku"].endswith("-H") else ""], 2)
            if surface <= 0:   # plaques des seules cloisons
                continue
            q["quantity"] += calc.margin_pieces(surface)
            q["formula"] += calc.margin_formula(surface)
            marges[q["name"]] = calc.margin_pieces(surface)
    if marges:
        steps.append(calc.CalcStep("Marge du patron", calc.MARGIN_RULE + " (faux plafond, surface couverte par chaque article ; "
                                   "cloisons : aucune)", {"plafonds_m2": ceiling_m2, "cloisons_m2": round(partition_m2, 2)},
                                   " ; ".join(f"{name} + {m}" for name, m in marges.items()), "pièces", calc.STATUS_CONFIRMED))

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
        "assumptions": assumptions + [f"Plaques {board_width:g} × {board_length:g} m comptées au plan de pose, pièce par pièce"
                                      + (f", + {waste * 100:.0f} % de chute" if waste else "")
                                      + f". Marge du patron sur les plaques, fourrures et cornières du faux plafond ({calc.MARGIN_RULE}, "
                                      "selon la surface de plafond couverte) ; cloisons, pivots, chevilles et vis au compte exact."],
        "missing": missing, "notes": [], "data_used": [], "inputs": {"surface_plafond_m2": total_ceiling},
        "next_step": "Prêt pour le devis.",
    }
