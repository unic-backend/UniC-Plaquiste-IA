"""Du plan au devis : les pièces lues sur le plan deviennent un métré, sans rien redemander au patron. Gros dossiers : chaque
pièce garde son niveau (une page par étage), un étage courant compte autant de fois que le plan le dit, une pièce en L est
calculée rectangle par rectangle, et chaque pièce reçoit sa consigne de pose (fourrures, tiges, plaques).

Plafonds : plaques calculées sur la surface TOTALE de chaque type (standard / hydrofuge) pour ne pas arrondir pièce par
pièce ; ossature et suspentes calculées pièce par pièce (elles dépendent des dimensions). Cloisons : longueur × hauteur.
Chaque pièce retenue, sa surface et sa source (plan) sont écrites dans les hypothèses du devis : tout est traçable.
"""
from __future__ import annotations

import math
import re
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


def room_label(p: dict) -> str:
    """Nom d'une pièce dans un dossier de plusieurs niveaux : « Chambre 1 — Appartement A (R+1) » (un même nom revient à chaque étage)."""
    return p["nom"] + (f" — {p['logement']}" if p.get("logement") else "") + (f" ({p['niveau']})" if p.get("niveau") else "")


def _pose(p: dict, rects: list[list[float]], board_width: float, board_length: float) -> dict:
    """Consigne de pose d'une pièce (règles du patron) : sens et nombre des fourrures, tiges, plaques entières et morceaux."""
    fourrures, tiges, entieres, morceaux = [], 0, 0, 0
    for a, b in rects:
        run, across = calc.ceiling_run(a, b)
        rows, hangers, _ = calc.ceiling_layout(run, across)
        laid = calc.ceiling_boards(a, b, None, board_width, board_length)
        fourrures.append(f"{rows} lignes dans le sens des {round(run, 2):g} m".replace(".", ","))
        tiges, entieres, morceaux = tiges + hangers, entieres + laid["entieres"], morceaux + laid["pour_morceaux"]
    return {"piece": room_label(p), "page": p.get("page"), "niveau": p.get("niveau"), "surface_m2": p.get("surface_m2"),
            "repetition": int(p.get("repetition") or 1), "zones": len(rects),
            "fourrures": " + ".join(fourrures) + " (tous les 50 cm, la première et la dernière contre le mur)",
            "tiges": tiges, "plaques": f"{entieres} entières + {morceaux} pour les morceaux = {entieres + morceaux}"}


# Laine : couverture d'un paquet supposée d'après le devis de référence du patron (1 paquet par paroi de 5,40 × 2,50 m) ; à confirmer
LAINE_M2_PAR_PAQUET = 13.5


def systeme(libelle: str) -> dict:
    """Système de cloison lu dans la légende : « Cloison 98/48 - 2 BA13 chaque face + laine 45 mm » → montants de 48, 2 plaques
    par face, laine de 45 mm ; « … BA13 hydro H1 (pièces humides) » → plaques hydrofuges ; « doublage » ou « 1 face » → une face."""
    low = libelle.lower()
    layers = re.search(r"(\d)\s*(?:x\s*)?ba\s?1[38]", low)
    frame = re.search(r"\b\d{2,3}\s*/\s*(\d{2,3})\b", low)
    wool = re.search(r"(?:laine|isolant)\D{0,25}?(\d{2,3})\s*mm", low)
    return {"couches": max(1, min(3, int(layers.group(1)))) if layers else 1,
            "ossature_mm": int(frame.group(1)) if frame else 48,
            "hydro": bool(re.search(r"hydro|\bh1\b|pi[eè]ces?\s+humides", low)),
            "laine_mm": int(wool.group(1)) if wool else (0 if not re.search(r"laine|isolant", low) else None),
            "faces": 1 if re.search(r"doublage|une\s+(?:seule\s+)?face|\b1\s*face\b", low) else 2}


def cloisons_mesurees(metre: dict, *, board_width: float = 1.2, board_length: float = 2.0, stud_spacing: float = 0.6,
                      fixings: dict | None = None) -> list[dict]:
    """Matériaux des cloisons MESURÉES sur le plan (metre_cloisons) : chaque tronçon est un mur (montants à chaque bout, plaques
    au plan de pose, rallonges et éclisses au-dessus de 2,80 m), répété sur ses niveaux à la hauteur du cartouche ; puis le
    système de la légende : plaques hydrofuges, 2 plaques par face, laine, ossature de 70. Pas de marge (règle du patron)."""
    walls: dict[str, list[tuple[float, float]]] = {}
    missing: list[str] = []
    for lv in metre.get("par_niveau") or []:
        h = lv.get("hauteur_m")
        if not h:
            missing.append(f"{lv.get('niveau') or 'page ' + str(lv.get('page'))} : hauteur des cloisons inconnue, non chiffrées.")
            continue
        for t in lv["types"]:
            runs = t.get("troncons_m") or ([t["ml_par_niveau"]] if t.get("ml_par_niveau") else [])
            walls.setdefault(t["libelle"], []).extend([(float(r), float(h)) for r in runs if r > 0] * int(lv.get("niveaux") or 1))
    out = []
    fx = calc.fixings(fixings)
    for label, ws in walls.items():
        if not ws:
            continue
        sy = systeme(label)
        res = calc.calculate_partition(ws[0][0], ws[0][1], sy["faces"], [], walls=ws, board_width=board_width,
                                       board_height=board_length, stud_spacing=stud_spacing, fixing_values=fixings,
                                       confirmed_large=True, openings_known=True)
        if sy["hydro"]:
            calc.make_hydrofuge(res, "Plaques hydrofuges : système de la légende (pièces humides).")
        for q in res.quantities:
            if q.sku.startswith("BA13-") and sy["couches"] > 1:
                q.quantity *= sy["couches"]
                q.formula += f" ; × {sy['couches']} plaques par face (légende)"
            elif q.sku == "VIS-PLAQUE" and sy["couches"] > 1:
                q.quantity *= sy["couches"]
                q.formula += f" ; × {sy['couches']} couches"
            elif q.sku == "MONTANT-M48" and sy["ossature_mm"] == 70:
                q.sku, q.name = "MONTANT-M70", q.name.replace("M48", "M70")
            elif q.sku == "UC-RAILS-48-MM" and sy["ossature_mm"] == 70:
                q.sku, q.name = "UC-RAILS-7-CM-70-MM", q.name.replace("48 mm", "70 mm")
        surface = round(sum(a * b for a, b in ws), 2)
        mm = sy["laine_mm"]
        if mm is None or mm:   # laine citée dans la légende (épaisseur lue si elle est écrite)
            res.quantities.append(calc.QuantityLine(
                "UC-LAINE-DE-VERRE-PAQUET", f"Laine de verre{f' {mm} mm' if mm else ''} (paquet)",
                calc.ceil_int(surface / LAINE_M2_PAR_PAQUET), "paquet",
                f"⌈ {surface:g} m² de cloison / {LAINE_M2_PAR_PAQUET:g} m² par paquet ⌉", calc.STATUS_ASSUMED,
                notes="couverture d'un paquet supposée (devis de référence : 1 paquet par paroi de 5,40 × 2,50 m) : à confirmer"))
        anchors = sum(calc.anchor_points(2 * a, 2, fx["anchor_spacing_m"]) for a, _ in ws)
        studs = int(next(st.result for st in res.steps if st.label.startswith("Nombre de montants")))
        out.append({"libelle": label, "systeme": sy, "result": res, "murs": len(ws), "ml": round(sum(a for a, _ in ws), 2),
                    "m2": surface, "chevilles": anchors, "vis9": studs * fx["screws9_per_stud"]})
    if missing:
        out.append({"manquant": missing})
    return out


def build(analysis: dict, *, rooms: list[str] | None = None, include_to_confirm: bool = False,
          hydrofuge_rooms: list[str] | None = None, partitions: list[dict] | None = None,
          waste: float = 0.0, board_width: float = 1.2, board_length: float = 2.0, stud_spacing: float = 0.6,
          fixings: dict | None = None, cloisons_du_plan: bool = False, plafonds: bool = True) -> dict:
    """Métré (format de CalcResult.to_dict) à partir de l'analyse du plan. Chaque pièce est comptée juste (plaques au plan de
    pose) ; la marge du patron (en pièces) est ajoutée UNE fois par article du faux plafond, selon la surface de plafond qu'il
    couvre sur tout le plan (plaques hydrofuges : les pièces humides). Cloisons : aucune marge (règle du patron)."""
    pieces = (analysis.get("pieces") or []) if plafonds else []   # plafonds=False : seulement les cloisons
    if not pieces and not partitions and not cloisons_du_plan:
        raise PlanQuoteError("Aucune pièce lue sur ce plan : relis le plan (read_plan) ou donne les dimensions.")
    hydro = hydrofuge_rooms or []
    if rooms and plafonds:
        chosen = [p for p in pieces if _match(room_label(p), rooms)]
        unknown = [r for r in rooms if not any(_match(room_label(p), [r]) for p in pieces)]
        if unknown:
            raise PlanQuoteError(f"Pièce(s) absente(s) du plan : {', '.join(unknown)}. Pièces lues : "
                                 + ", ".join(room_label(p) for p in pieces[:80]))
    else:
        flags = {"oui", "a_confirmer"} if include_to_confirm else {"oui"}
        chosen = [p for p in pieces if p.get("plafond") in flags]
        if pieces and not chosen and not partitions and not cloisons_du_plan:
            raise PlanQuoteError("Le plan ne confirme aucun plafond : demande au patron quelles pièces ont un faux plafond "
                                 "(ou include_to_confirm=true s'il dit « toutes »).")

    steps, assumptions, missing = [], [], []
    unread = (analysis.get("lecture") or {}).get("non_lues") or []
    if unread:
        missing.append(f"Pages du plan non lues : {', '.join(map(str, unread))} (relis le plan) : leurs pièces ne sont pas comptées.")
    others: dict[str, dict] = {}
    area_by_type = {"": 0.0, "-H": 0.0}
    boards_by_type = {"": 0, "-H": 0}   # plaques au plan de pose, pièce par pièce
    partition_m2 = 0.0
    pose: list[dict] = []          # consigne de pose de chaque pièce, pour les ouvriers
    levels: dict[str, dict] = {}   # totaux par niveau (étage), répétitions comprises
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
        name = room_label(p)
        area = p.get("surface_m2")
        if not area:
            missing.append(f"{name} : surface non lisible sur le plan, non comptée.")
            continue
        rep = max(1, int(p.get("repetition") or 1))   # « étage courant R+1 à R+4 » : le même plan compte 4 fois
        L, l = p.get("longueur_m"), p.get("largeur_m")
        rects = [list(r) for r in p.get("rectangles") or []]   # pièce en L ou couloir coudé : découpée en rectangles
        if not rects:
            if not (L and l):
                L = l = math.sqrt(area)
                assumptions.append(f"{name} : dimensions non cotées, ossature estimée sur un carré de {area:g} m².")
            rects = [[L, l]]
        suffix = "-H" if _match(name, hydro) else ""
        area_by_type[suffix] += area * rep
        res = calc.calculate_ceiling(rects[0][0], rects[0][1], zones=rects if len(rects) > 1 else None, waste=waste,
                                     board_width=board_width, board_height=board_length, fixing_values=fixings, margin=False)
        boards_by_type[suffix] += int(next(q.quantity for q in res.quantities if q.sku.startswith("BA13-"))) * rep
        hangers = step_result(res, "Points d'accroche")
        count("UC-PIVOT", hangers * rep)
        count("UC-CHEVILLES-A-LETON", hangers * rep)
        count("UC-PAQUET-CHEVILLES-A-FRAPPER", sum(calc.anchor_points(2 * (a + b), 4, fx["anchor_spacing_m"]) for a, b in rects) * rep)
        for q in res.quantities:
            if not q.sku.startswith("BA13-"):   # plaques comptées plus bas, sur le total
                add(calc.QuantityLine(**{**asdict(q), "quantity": q.quantity * rep}))
        times = f" × {rep} logements" if str(p.get("logement") or "").startswith("Type ") else f" × {rep} étages identiques"
        steps.append(calc.CalcStep(f"Plafond {name}" + (times if rep > 1 else "") + (" (hydrofuge)" if suffix else ""),
                                   "surface lue sur le plan", {"page": p.get("page") or 1, **({"niveau": p["niveau"]} if p.get("niveau") else {})},
                                   area, "m²", calc.STATUS_CONFIRMED))
        assumptions.append(f"{name} : {area:g} m² (plan" + (f", p. {p['page']}" if p.get("page") else "")
                           + (f",{times}" if rep > 1 else "") + (", hydrofuge" if suffix else "") + ").")
        pose.append(_pose(p, rects, board_width, board_length))
        lv = levels.setdefault(p.get("niveau") or f"page {p.get('page') or 1}", {"niveau": p.get("niveau") or f"page {p.get('page') or 1}",
                                                                                "pieces": 0, "surface_m2": 0.0, "repetition": rep})
        lv["pieces"] += 1
        lv["surface_m2"] = round(lv["surface_m2"] + area * rep, 2)

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

    if cloisons_du_plan:   # cloisons mesurées sur le plan (traits de la légende), matériaux mur par mur
        if not analysis.get("metre_cloisons"):
            raise PlanQuoteError("Aucune cloison mesurée sur ce plan (pas de légende de cloisons ou pas d'échelle) : "
                                 "donne les longueurs et la hauteur des cloisons.")
        for t in cloisons_mesurees(analysis["metre_cloisons"], board_width=board_width, board_length=board_length,
                                   stud_spacing=stud_spacing, fixings=fixings):
            if "manquant" in t:
                missing += t["manquant"]
                continue
            count("UC-PAQUET-CHEVILLES-A-FRAPPER", t["chevilles"])
            count("UC-VIS-9-MM", t["vis9"])
            for q in t["result"].quantities:
                add(q)
            partition_m2 += t["m2"]
            sy = t["systeme"]
            steps.append(calc.CalcStep(f"Cloisons mesurées : {t['libelle']}", "Σ tronçons × hauteur × niveaux concernés",
                                       {"ml": t["ml"], "murs": t["murs"]}, t["m2"], "m²", calc.STATUS_CALCULATED))
            assumptions.append(f"{t['libelle']} : {t['ml']:g} ml, {t['m2']:g} m² ({t['murs']} murs, niveaux compris) ; "
                               f"{sy['faces']} face(s), {sy['couches']} plaque(s) par face"
                               + (", plaques hydrofuges" if sy["hydro"] else "") + (f", laine {sy['laine_mm']} mm" if sy["laine_mm"] else "")
                               + f", montants de {sy['ossature_mm']} ; pas de marge sur les cloisons.")

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
                         f"{total_ceiling:g} m²" + (f" sur {len(levels)} niveaux" if len(levels) > 1 else "")
                         + (f", {len(partitions or [])} cloison(s)" if partitions else "") + ".",
        "steps": [asdict(s) for s in steps], "quantities": quantities,
        "assumptions": assumptions + [f"Plaques {board_width:g} × {board_length:g} m comptées au plan de pose, pièce par pièce"
                                      + (f", + {waste * 100:.0f} % de chute" if waste else "")
                                      + f". Marge du patron sur les plaques, fourrures et cornières du faux plafond ({calc.MARGIN_RULE}, "
                                      "selon la surface de plafond couverte) ; cloisons, pivots, chevilles et vis au compte exact."],
        "missing": missing, "notes": [], "data_used": [], "inputs": {"surface_plafond_m2": total_ceiling},
        "pose": pose, "niveaux": list(levels.values()),
        "next_step": "Prêt pour le devis.",
    }
