"""Moteur de calcul BTP UniC Plaquiste.

Toutes les formules sont exposées. Aucun prix n'est inventé.
Les coefficients de déchet / entraxe sont des HYPOTHÈSES configurables
tant qu'ils n'ont pas été saisis dans la base UniC.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any


STATUS_CONFIRMED = "confirmed"
STATUS_ESTIMATED = "estimated"
STATUS_ASSUMED = "assumed"
STATUS_MISSING = "missing"

DEFAULTS = {
    "board_width_m": 1.20,
    "board_height_m": 2.00,
    "waste": 0.08,
    "stud_spacing_m": 0.60,
    "screws_per_m2": 15.0,
    "tape_m_per_m2": 1.40,
    "compound_kg_per_m2_per_coat": 0.35,
    "compound_coats": 2,
    "paint_l_per_m2_per_coat": 0.10,
    "paint_coats": 2,
    "primer_l_per_m2": 0.08,
    "ceiling_tile_side_m": 0.60,
    "hanger_spacing_m": 0.90,    # méthode UniC : une tige tous les 0,90 m le long de chaque fourrure
    "furring_spacing_m": 0.50,
    "bar_length_m": 2.90,        # fourrures, montants, rails, cornières : barres de 2,90 m   # méthode UniC : fourrures tous les 0,50 m (plaque de 2 m posée en travers : 4 appuis, joints sur fourrure)
}


BAR_LENGTH_M = 2.90   # longueur des barres UniC (fourrure, montant, rail, cornière)


def board_sku(board_width_m: float, board_height_m: float, suffix: str = "") -> tuple[str, str]:
    """Référence et libellé de la plaque selon ses dimensions (2 m × 1,20 m, 2,50 m × 1,20 m…) : chaque taille a son prix."""
    h, w = int(round(board_height_m * 1000)), int(round(board_width_m * 1000))
    return f"BA13-{h}x{w}{suffix}", f"Plaque de plâtre BA13 {h}×{w}"


@dataclass
class Opening:
    kind: str
    width: float
    height: float
    quantity: int = 1

    @property
    def area(self) -> float:
        return self.width * self.height * self.quantity


@dataclass
class CalcStep:
    label: str
    formula: str
    inputs: dict[str, Any]
    result: float | int | str
    unit: str = ""
    status: str = STATUS_CONFIRMED


@dataclass
class QuantityLine:
    sku: str
    name: str
    quantity: float
    unit: str
    formula: str = ""
    status: str = STATUS_ESTIMATED
    notes: str = ""
    waste_included: bool = True


@dataclass
class CalcResult:
    kind: str
    title: str
    understanding: str
    steps: list[CalcStep] = field(default_factory=list)
    quantities: list[QuantityLine] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    data_used: list[dict[str, Any]] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "understanding": self.understanding,
            "steps": [asdict(s) for s in self.steps],
            "quantities": [asdict(q) for q in self.quantities],
            "assumptions": self.assumptions,
            "missing": self.missing,
            "notes": self.notes,
            "data_used": self.data_used,
            "inputs": self.inputs,
            "next_step": self.next_step,
        }


def ceil_int(value: float) -> int:
    if value <= 0:
        return 0
    return int(math.ceil(value - 1e-9))


def round_qty(value: float, ndigits: int = 2) -> float:
    return round(value + 0.0, ndigits)


def board_area(width: float, height: float) -> float:
    return width * height


def partition_area(
    length_m: float,
    height_m: float,
    sides: int = 1,
    openings: list[Opening] | None = None,
) -> dict[str, float]:
    if length_m < 0 or height_m < 0:
        raise ValueError("Les dimensions doivent être positives")
    if sides not in (1, 2):
        raise ValueError("Le nombre de faces doit être 1 ou 2")
    gross = length_m * height_m * sides
    opening_one_face = sum(o.area for o in openings or [])
    opening_total = opening_one_face * sides
    net = max(gross - opening_total, 0.0)
    return {
        "gross": round_qty(gross, 3),
        "openings": round_qty(opening_total, 3),
        "net": round_qty(net, 3),
    }


def boards_needed(net_area: float, waste: float, board_m2: float) -> int:
    if board_m2 <= 0:
        raise ValueError("Surface de plaque invalide")
    return ceil_int(net_area * (1.0 + waste) / board_m2)


def studs_needed(length_m: float, spacing_m: float) -> int:
    if spacing_m <= 0:
        raise ValueError("Entraxe invalide")
    # montants d'extrémité inclus : floor(L/e) + 1
    return int(math.floor(length_m / spacing_m + 1e-9)) + 1   # 1e-9 : évite 6,999… pour 7


def tracks_length(length_m: float, runs: int = 2) -> float:
    return round_qty(length_m * runs, 3)


MAX_SURFACE_M2 = 10_000.0   # au-delà : probablement une faute de frappe (unité, virgule) → confirmation explicite


def check_inputs(*, positive: dict[str, float] | None = None, surface_m2: float | None = None,
                 waste: float | None = None, confirmed_large: bool = False) -> None:
    """Refuse les saisies physiquement impossibles (valeurs ≤ 0, non numériques, surface démesurée)."""
    for name, v in (positive or {}).items():
        if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v <= 0:
            raise ValueError(f"« {name} » doit être un nombre strictement positif (reçu : {v}).")
    if waste is not None and not 0 <= waste <= 0.5:
        raise ValueError(f"Le taux de chute doit être entre 0 % et 50 % (reçu : {waste:.0%}).")
    if surface_m2 is not None and surface_m2 > MAX_SURFACE_M2 and not confirmed_large:
        raise ValueError(f"Surface de {surface_m2:,.0f} m² : au-delà de {MAX_SURFACE_M2:,.0f} m² pour un seul calcul. "
                         "Vérifie les unités (m ou mm ?) puis confirme, ou découpe en plusieurs chantiers.".replace(",", " "))


def calculate_partition(
    length_m: float,
    height_m: float,
    sides: int = 2,
    openings: list[Opening] | None = None,
    *,
    waste: float = DEFAULTS["waste"],
    board_width: float = DEFAULTS["board_width_m"],
    board_height: float = DEFAULTS["board_height_m"],
    stud_spacing: float = DEFAULTS["stud_spacing_m"],
    include_finish: bool = True,
    confirmed_large: bool = False,
) -> CalcResult:
    openings = openings or []
    check_inputs(positive={"longueur": length_m, "hauteur": height_m, "largeur de plaque": board_width,
                           "hauteur de plaque": board_height, "entraxe": stud_spacing},
                 surface_m2=length_m * height_m * sides, waste=waste, confirmed_large=confirmed_large)
    b_area = board_area(board_width, board_height)
    areas = partition_area(length_m, height_m, sides, openings)
    n_boards = boards_needed(areas["net"], waste, b_area)
    n_studs = studs_needed(length_m, stud_spacing)
    tracks = tracks_length(length_m, 2)
    # montants : un par montant, hauteur = hauteur cloison
    stud_ml = round_qty(n_studs * height_m, 3)
    screws = ceil_int(areas["net"] * DEFAULTS["screws_per_m2"])
    tape = round_qty(areas["net"] * DEFAULTS["tape_m_per_m2"], 2)
    compound = round_qty(
        areas["net"] * DEFAULTS["compound_kg_per_m2_per_coat"] * DEFAULTS["compound_coats"],
        2,
    )

    result = CalcResult(
        kind="partition",
        title="Calcul de cloison / plaquisterie",
        understanding=(
            f"Cloison de {length_m:g} m de long × {height_m:g} m de haut, "
            f"{sides} face(s)"
            + (f", {len(openings)} ouverture(s)" if openings else "")
            + "."
        ),
        inputs={
            "length_m": length_m,
            "height_m": height_m,
            "sides": sides,
            "openings": [asdict(o) for o in openings],
            "waste": waste,
            "board_width": board_width,
            "board_height": board_height,
            "stud_spacing": stud_spacing,
        },
        next_step="Je peux transformer ces quantités en devis, bon de commande ou rapport.",
    )

    result.data_used = [
        {"label": "Longueur", "value": length_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "Hauteur", "value": height_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "Faces", "value": sides, "unit": "", "status": STATUS_CONFIRMED},
        {
            "label": "Plaque",
            "value": f"{board_width:g} × {board_height:g}",
            "unit": "m",
            "status": STATUS_ASSUMED,
        },
        {"label": "Déchet", "value": waste * 100, "unit": "%", "status": STATUS_ASSUMED},
        {"label": "Entraxe montants", "value": stud_spacing, "unit": "m", "status": STATUS_ASSUMED},
    ]

    result.steps = [
        CalcStep(
            "Surface brute",
            "longueur × hauteur × faces",
            {"longueur": length_m, "hauteur": height_m, "faces": sides},
            areas["gross"],
            "m²",
            STATUS_CONFIRMED,
        ),
        CalcStep(
            "Surface des ouvertures",
            "Σ (largeur × hauteur × qté) × faces",
            {"ouvertures": [asdict(o) for o in openings], "faces": sides},
            areas["openings"],
            "m²",
            STATUS_CONFIRMED,
        ),
        CalcStep(
            "Surface nette",
            "surface brute − ouvertures",
            {"brute": areas["gross"], "ouvertures": areas["openings"]},
            areas["net"],
            "m²",
            STATUS_CONFIRMED,
        ),
        CalcStep(
            "Surface d'une plaque",
            "largeur × hauteur",
            {"largeur": board_width, "hauteur": board_height},
            round_qty(b_area, 3),
            "m²",
            STATUS_ASSUMED,
        ),
        CalcStep(
            "Nombre de plaques",
            "⌈ surface nette × (1 + déchet) / surface plaque ⌉",
            {"nette": areas["net"], "dechet": waste, "plaque": b_area},
            n_boards,
            "u",
            STATUS_ESTIMATED,
        ),
        CalcStep(
            "Nombre de montants",
            "⌊ longueur / entraxe ⌋ + 1",
            {"longueur": length_m, "entraxe": stud_spacing},
            n_studs,
            "u",
            STATUS_ESTIMATED,
        ),
        CalcStep(
            "Longueur de montants",
            "nombre de montants × hauteur",
            {"nombre": n_studs, "hauteur": height_m},
            stud_ml,
            "ml",
            STATUS_ESTIMATED,
        ),
        CalcStep(
            "Rails (haut + bas)",
            "longueur × 2",
            {"longueur": length_m},
            tracks,
            "ml",
            STATUS_ESTIMATED,
        ),
    ]

    result.quantities = [
        QuantityLine(*board_sku(board_width, board_height), n_boards, "u",
                     "⌈Snette×(1+d)/Splaque⌉", STATUS_ESTIMATED),
        QuantityLine("MONTANT-M48", "Montant M48", n_studs, "u",
                     "⌊L/entraxe⌋+1", STATUS_ESTIMATED, notes=f"Soit {stud_ml} ml à la hauteur {height_m:g} m"),
        QuantityLine("UC-RAILS-48-MM", "Rails 48 mm (barre de 2,90 m, haut + bas)", ceil_int(tracks / BAR_LENGTH_M), "barre",
                     "⌈ L × 2 / 2,90 ⌉", STATUS_ESTIMATED),
        QuantityLine("VIS-PLAQUE", "Vis à plaque", screws, "u",
                     f"Snette×{DEFAULTS['screws_per_m2']:g}", STATUS_ASSUMED),
    ]
    if include_finish:
        result.quantities += [
            QuantityLine("BANDE-JOINT", "Bande à joint", tape, "ml",
                         f"Snette×{DEFAULTS['tape_m_per_m2']:g}", STATUS_ASSUMED),
            QuantityLine("ENDUIT-JOINT", "Enduit à joint", compound, "kg",
                         f"Snette×{DEFAULTS['compound_kg_per_m2_per_coat']:g}×{DEFAULTS['compound_coats']}",
                         STATUS_ASSUMED),
        ]

    result.assumptions = [
        f"Plaque standard BA13 {board_width:g} × {board_height:g} m = {b_area:.2f} m² (catalogue par défaut, non une donnée UniC confirmée).",
        f"Coefficient de déchet = {waste*100:.0f} % (paramètre par défaut, à confirmer selon la complexité du chantier).",
        f"Entraxe des montants = {stud_spacing:g} m (paramètre par défaut).",
        f"Vis = {DEFAULTS['screws_per_m2']:g} / m² (règle professionnelle par défaut).",
        "Les montants d'ouverture (renforts autour des portes/fenêtres) ne sont pas ajoutés automatiquement.",
        "Aucun prix n'est appliqué : les tarifs UniC ne sont pas inventés.",
    ]
    result.missing = [
        "Prix d'achat et de vente des matériaux (absents de la base UniC tant qu'ils n'ont pas été saisis).",
        "Main-d'œuvre : taux horaire non renseigné.",
        "Transport / livraison : non chiffré.",
    ]
    if not openings:
        result.missing.append("Ouvertures (portes, fenêtres) non déduites — non communiquées.")
    result.notes = [
        "Les quantités de plaques et d'ossature sont des ESTIMATIONS arrondies à l'unité supérieure.",
        "Vérifier la hauteur réelle des locaux : si H > hauteur de plaque, prévoir chutes / bandes de rive.",
    ]
    return result


def calculate_ceiling(
    length_m: float,
    width_m: float,
    *,
    waste: float = DEFAULTS["waste"],
    board_width: float = DEFAULTS["board_width_m"],
    board_height: float = DEFAULTS["board_height_m"],
    system: str = "ba13",
    confirmed_large: bool = False,
) -> CalcResult:
    check_inputs(positive={"longueur": length_m, "largeur": width_m, "largeur de plaque": board_width,
                           "hauteur de plaque": board_height},
                 surface_m2=length_m * width_m, waste=waste, confirmed_large=confirmed_large)
    area = round_qty(length_m * width_m, 3)
    b_area = board_area(board_width, board_height)
    n_boards = boards_needed(area, waste, b_area)
    # Fourrures parallèles à la longueur, espacées de 0,50 m sur la largeur ; tiges tous les 0,90 m sur chaque fourrure.
    # Sens de pose retenu : celui qui demande le moins de tiges (fourrures dans le sens le plus économique).
    f_sp, h_sp = DEFAULTS["furring_spacing_m"], DEFAULTS["hanger_spacing_m"]

    def layout(run: float, across: float) -> tuple[int, int, float]:
        rows_ = ceil_int(across / f_sp) + 1
        return rows_, rows_ * (ceil_int(run / h_sp) + 1), round_qty(run * rows_, 2)

    rows, hangers, furring_ml = min(layout(length_m, width_m), layout(width_m, length_m), key=lambda t: (t[1], t[2]))

    result = CalcResult(
        kind="ceiling",
        title="Calcul de faux plafond",
        understanding=f"Faux plafond {length_m:g} × {width_m:g} m, système {system}.",
        inputs={
            "length_m": length_m,
            "width_m": width_m,
            "waste": waste,
            "system": system,
        },
        next_step="Je peux préparer un devis quantité ou un bon de commande matériaux.",
    )
    result.data_used = [
        {"label": "Longueur", "value": length_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "Largeur", "value": width_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "Système", "value": system, "unit": "", "status": STATUS_ASSUMED},
        {"label": "Déchet", "value": waste * 100, "unit": "%", "status": STATUS_ASSUMED},
    ]
    result.steps = [
        CalcStep("Surface", "longueur × largeur",
                 {"longueur": length_m, "largeur": width_m}, area, "m²", STATUS_CONFIRMED),
        CalcStep("Nombre de plaques", "⌈ S × (1+d) / Splaque ⌉",
                 {"S": area, "d": waste, "Splaque": b_area}, n_boards, "u", STATUS_ESTIMATED),
        CalcStep("Lignes de fourrure (entraxe 0,50 m)", "⌈ côté / 0,50 ⌉ + 1", {"entraxe": f_sp}, rows, "u", STATUS_ESTIMATED),
        CalcStep("Points d'accroche (tige + pivot + cheville à laiton)",
                 "lignes × (⌈ longueur de fourrure / 0,90 ⌉ + 1)",
                 {"lignes": rows, "e": h_sp}, hangers, "u", STATUS_ESTIMATED),
    ]
    result.quantities = [
        QuantityLine(*board_sku(board_width, board_height), n_boards, "u",
                     "⌈S×(1+d)/Splaque⌉", STATUS_ESTIMATED),
        # point d'accroche UniC = 1 tige + 1 pivot + 1 cheville à laiton (pivots et chevilles vendus par paquet de 100)
        QuantityLine("UC-TIGES-A-L-UNITE", "Tiges (à l'unité)", hangers, "u",
                     "1 tige tous les 0,90 m sur chaque fourrure", STATUS_ESTIMATED),
        QuantityLine("UC-PIVOT", "Pivot (paquet de 100)", ceil_int(hangers / 100), "paquet",
                     f"⌈{hangers} points / 100⌉", STATUS_ASSUMED),
        QuantityLine("UC-CHEVILLES-A-LETON", "Chevilles à laiton (paquet de 100)", ceil_int(hangers / 100), "paquet",
                     f"⌈{hangers} points / 100⌉", STATUS_ASSUMED),
        QuantityLine("UC-BARRE-DE-FOURRURE-2-90-M", "Barre de fourrure (2,90 m)", ceil_int(furring_ml / BAR_LENGTH_M), "barre",
                     f"⌈ {furring_ml:g} ml ({rows} lignes, entraxe 0,50 m) / 2,90 ⌉", STATUS_ESTIMATED),
    ]
    result.assumptions = [
        f"Système par défaut : plaques BA13 {board_width:g}×{board_height:g} m.",
        f"Déchet {waste*100:.0f} %.",
        "Méthode UniC : fourrures tous les 0,50 m, une tige tous les 0,90 m (tige + pivot + cheville à laiton), "
        "plaques de 2 m posées en travers des fourrures.",
        "Les profils périphériques et les entretoises ne sont pas détaillés pièce par pièce.",
        "Aucun prix n'est appliqué.",
    ]
    result.missing = [
        "Type exact de faux plafond (BA13, dalles 600×600, démontable, acoustique) si différent du défaut.",
        "Hauteur de plénum / type de suspente.",
        "Prix UniC non renseignés.",
    ]
    return result


def calculate_paint(
    area_m2: float,
    coats: int = 2,
    include_primer: bool = True,
    consumption: float = DEFAULTS["paint_l_per_m2_per_coat"],
    confirmed_large: bool = False,
) -> CalcResult:
    check_inputs(positive={"surface": area_m2, "couches": coats, "consommation": consumption},
                 surface_m2=area_m2, confirmed_large=confirmed_large)
    paint_l = round_qty(area_m2 * coats * consumption, 2)
    primer_l = round_qty(area_m2 * DEFAULTS["primer_l_per_m2"], 2) if include_primer else 0.0
    result = CalcResult(
        kind="paint",
        title="Calcul de peinture",
        understanding=f"Peinture sur {area_m2:g} m², {coats} couche(s)"
        + (" + impression" if include_primer else "")
        + ".",
        inputs={"area_m2": area_m2, "coats": coats, "include_primer": include_primer,
                "consumption": consumption},
        next_step="Indiquez le produit UniC réellement utilisé pour chiffrer le prix.",
    )
    result.steps = [
        CalcStep("Peinture", "surface × couches × consommation",
                 {"S": area_m2, "couches": coats, "conso": consumption},
                 paint_l, "L", STATUS_ESTIMATED),
    ]
    result.quantities = [
        QuantityLine("PEINTURE", "Peinture (produit à préciser)", paint_l, "L",
                     "S×couches×conso", STATUS_ASSUMED),
    ]
    if include_primer:
        result.steps.append(
            CalcStep("Impression", "surface × consommation impression",
                     {"S": area_m2, "conso": DEFAULTS["primer_l_per_m2"]},
                     primer_l, "L", STATUS_ASSUMED)
        )
        result.quantities.append(
            QuantityLine("IMPRESSION", "Impression / primaire", primer_l, "L",
                         "S×0,08", STATUS_ASSUMED)
        )
    result.assumptions = [
        f"Consommation peinture = {consumption:g} L/m²/couche (hypothèse, à remplacer par la fiche produit).",
        "Aucune perte de matériel (rouleaux, bacs) n'est chiffrée.",
        "Aucun prix n'est appliqué.",
    ]
    result.missing = [
        "Référence commerciale de la peinture UniC.",
        "Nombre de couches réel prévu au CCTP.",
        "Prix au litre.",
    ]
    result.data_used = [
        {"label": "Surface", "value": area_m2, "unit": "m²", "status": STATUS_CONFIRMED},
        {"label": "Couches", "value": coats, "unit": "", "status": STATUS_CONFIRMED},
    ]
    return result


def calculate_plaster(area_m2: float, thickness_mm: float = 10.0, waste: float = 0.10,
                      confirmed_large: bool = False) -> CalcResult:
    check_inputs(positive={"surface": area_m2, "épaisseur": thickness_mm}, surface_m2=area_m2,
                 waste=waste, confirmed_large=confirmed_large)
    # 10 mm → 10 L/m² → ~10 kg/m² selon produit ; on reste en kg avec 1 kg ≈ 1 L hypothèse
    kg = round_qty(area_m2 * thickness_mm * (1.0 + waste), 2)
    result = CalcResult(
        kind="plaster",
        title="Calcul d'enduit / plâtre",
        understanding=f"Enduit sur {area_m2:g} m², épaisseur {thickness_mm:g} mm.",
        inputs={"area_m2": area_m2, "thickness_mm": thickness_mm, "waste": waste},
        next_step="Précisez le produit (enduit projeté, lissage, plâtre traditionnel) pour affiner.",
    )
    result.steps = [
        CalcStep(
            "Quantité",
            "surface × épaisseur_mm × (1 + déchet)   [hypothèse 1 mm ≈ 1 kg/m²]",
            {"S": area_m2, "e": thickness_mm, "d": waste},
            kg,
            "kg",
            STATUS_ASSUMED,
        )
    ]
    result.quantities = [
        QuantityLine("ENDUIT", "Enduit / plâtre (produit à préciser)", kg, "kg",
                     "S×e×(1+d)", STATUS_ASSUMED),
    ]
    result.assumptions = [
        "Conversion 1 mm d'épaisseur ≈ 1 kg/m² (ordre de grandeur, PAS une donnée produit UniC).",
        f"Déchet {waste*100:.0f} %.",
    ]
    result.missing = ["Produit exact et rendement fiche technique.", "Prix UniC."]
    result.data_used = [
        {"label": "Surface", "value": area_m2, "unit": "m²", "status": STATUS_CONFIRMED},
        {"label": "Épaisseur", "value": thickness_mm, "unit": "mm", "status": STATUS_ASSUMED},
    ]
    return result


def calculate_surface(length_m: float, width_or_height_m: float, extra_factor: float = 1.0,
                      confirmed_large: bool = False) -> CalcResult:
    check_inputs(positive={"longueur": length_m, "largeur/hauteur": width_or_height_m, "facteur": extra_factor},
                 surface_m2=length_m * width_or_height_m * extra_factor, confirmed_large=confirmed_large)
    area = round_qty(length_m * width_or_height_m * extra_factor, 3)
    result = CalcResult(
        kind="surface",
        title="Calcul de surface",
        understanding=f"Surface {length_m:g} × {width_or_height_m:g}"
        + (f" × {extra_factor:g}" if extra_factor != 1 else "")
        + ".",
        inputs={"a": length_m, "b": width_or_height_m, "factor": extra_factor},
        next_step="Je peux en déduire plaques, peinture ou un devis.",
    )
    result.steps = [
        CalcStep("Surface", "a × b × facteur",
                 {"a": length_m, "b": width_or_height_m, "facteur": extra_factor},
                 area, "m²", STATUS_CONFIRMED),
    ]
    result.data_used = [
        {"label": "a", "value": length_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "b", "value": width_or_height_m, "unit": "m", "status": STATUS_CONFIRMED},
    ]
    return result


# ---------- parsing from natural language ----------

_NUM = r"(?:(?:\d{1,3}(?:[ \u00a0]\d{3})+)|(?:\d+))(?:[.,]\d+)?"


def parse_number(raw: str) -> float:
    s = raw.strip().replace("\u00a0", " ").replace(" ", "")
    s = s.replace(",", ".")
    return float(s)


def _find_numbers(text: str) -> list[float]:
    return [parse_number(m.group(0)) for m in re.finditer(_NUM, text)]


def _extract_dimension_pair(text: str) -> tuple[float, float] | None:
    t = text.lower().replace("×", "x").replace("*", "x")
    m = re.search(
        rf"({_NUM})\s*(?:m|ml|mètres?|metres?)?\s*(?:[x/]|sur|par)\s*({_NUM})\s*(?:m|ml)?",
        t,
        re.I,
    )
    if m:
        return parse_number(m.group(1)), parse_number(m.group(2))
    m = re.search(rf"({_NUM})\s*m2|({_NUM})\s*m²", t, re.I)
    return None


def _sides(text: str) -> int:
    t = text.lower()
    if re.search(r"deux\s+faces|2\s+faces|both\s+sides|double\s+peau|des deux", t):
        return 2
    if re.search(r"une\s+face|1\s+face|one\s+side|simple\s+peau", t):
        return 1
    return 2


def _openings(text: str) -> list[Opening]:
    t = text.lower()
    openings: list[Opening] = []
    door_q = re.search(r"(\d+)\s*(?:portes?|doors?)", t)
    win_q = re.search(r"(\d+)\s*(?:fen[eê]tres?|windows?)", t)
    # door size e.g. porte 0.90 x 2.04
    for kind, default_w, default_h, patt in (
        ("door", 0.90, 2.04, r"porte[s]?\s+(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)"),
        ("window", 1.20, 1.20, r"fen[eê]tre[s]?\s+(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)"),
    ):
        for m in re.finditer(patt, t):
            openings.append(Opening(kind, parse_number(m.group(1)), parse_number(m.group(2)), 1))
    if door_q and not any(o.kind == "door" for o in openings):
        openings.append(Opening("door", 0.90, 2.04, int(door_q.group(1))))
    if win_q and not any(o.kind == "window" for o in openings):
        openings.append(Opening("window", 1.20, 1.20, int(win_q.group(1))))
    return openings


def detect_calc_kind(text: str) -> str | None:
    t = text.lower()
    if re.search(r"faux[\s-]?plafond|suspended ceiling|plafond suspendu", t):
        return "ceiling"
    if re.search(r"peinture|paint|peintur", t):
        return "paint"
    if re.search(r"plafond", t) and not re.search(r"cloison|doublage", t):
        return "ceiling"
    if re.search(r"enduit|pl[aâ]tre(?!rie)|plaster(?!board)", t) and not re.search(
        r"plaque|placo|ba13|cloison", t
    ):
        return "plaster"
    if re.search(
        r"cloison|plaqu|placo|ba13|ba 13|drywall|partition|doublage|ossature|montant|rail",
        t,
    ):
        return "partition"
    if re.search(r"surface|superficie|aire|m²|m2|combien de plaques|how many boards", t):
        return "surface"
    return None


def calculate_from_text(text: str, defaults: dict | None = None) -> CalcResult | None:
    cfg = {**DEFAULTS, **(defaults or {})}
    kind = detect_calc_kind(text)
    if kind is None:
        return None
    t = text.lower().replace("×", "x")
    if re.search(r"plaques?\s*(?:de\s*)?(?:2[.,]50?|2500)\b", t):
        cfg["board_height_m"] = 2.5   # seulement si le patron le précise : la plaque par défaut fait 2 m
    t = re.sub(r"\b(?:ba|bs)\s?\d{1,2}\b", " ", t)  # références produit (BA13, BA 18) : pas des dimensions

    pair = _extract_dimension_pair(t)
    nums = _find_numbers(t)
    area_m = None
    m_area = re.search(rf"({_NUM})\s*(?:m²|m2)", t)
    if m_area:
        area_m = parse_number(m_area.group(1))

    length = re.search(rf"(?:long(?:ueur)?|length)\s*[:=]?\s*({_NUM})", t)
    height = re.search(rf"(?:haut(?:eur)?|height|h)\s*[:=]?\s*({_NUM})", t)
    width = re.search(rf"(?:larg(?:eur)?|width|l)\s*[:=]?\s*({_NUM})", t)

    waste = cfg["waste"]
    wm = re.search(rf"(?:d[ée]chet|waste)\s*[:=]?\s*({_NUM})\s*%?", t)
    if wm:
        w = parse_number(wm.group(1))
        waste = w / 100.0 if w > 1 else w

    if kind == "partition":
        L = H = None
        if pair:
            L, H = pair
            if H > 6 and L <= 6:
                L, H = H, L  # 2.5 x 320 → likely height x length swapped if one is wall length
            if L < H and L <= 4.5 and H > 6:
                L, H = H, L
        if length:
            L = parse_number(length.group(1))
        if height:
            H = parse_number(height.group(1))
        if L is None and nums:
            L = nums[0]
        if H is None:
            H = nums[1] if len(nums) > 1 else 2.50
        if L is not None and (H > 8 or L > 2000):
            return CalcResult(
                kind="partition", title="Calcul de cloison",
                understanding=f"Dimensions peu crédibles ({L:g} x {H:g} m) : je préfère ne pas calculer.",
                missing=["Longueur et hauteur de la cloison en mètres."],
                next_step="Indiquez par exemple : cloison 12 x 2,5 m.",
            )
        if L is None:
            return CalcResult(
                kind="partition", title="Calcul de cloison",
                understanding="Cloison détectée, longueur manquante.",
                missing=["Longueur de la cloison."],
                next_step="Indiquez par exemple : cloison 12 x 2,5 m.",
            )
        return calculate_partition(
            L, H, sides=_sides(t), openings=_openings(t), waste=waste,
            board_width=cfg["board_width_m"], board_height=cfg["board_height_m"],
            stud_spacing=cfg["stud_spacing_m"],
        )

    if kind == "ceiling":
        if pair:
            a, b = pair
        elif length and width:
            a, b = parse_number(length.group(1)), parse_number(width.group(1))
        elif area_m is not None:
            side = math.sqrt(area_m)
            a, b = round(side, 3), round(area_m / side, 3)
        elif len(nums) >= 2:
            a, b = nums[0], nums[1]
        else:
            return CalcResult(
                kind="ceiling",
                title="Calcul de faux plafond",
                understanding="Demande de faux plafond détectée, dimensions manquantes.",
                missing=["Longueur et largeur (ou surface) du plafond."],
                next_step="Indiquez par exemple : faux plafond 8 x 5 m.",
            )
        return calculate_ceiling(a, b, waste=waste, board_width=cfg["board_width_m"],
                                 board_height=cfg["board_height_m"])

    if kind == "paint":
        if area_m is None:
            if pair:
                area_m = pair[0] * pair[1]
            elif len(nums) >= 1:
                area_m = nums[0]
            else:
                return CalcResult(
                    kind="paint", title="Calcul de peinture",
                    understanding="Demande de peinture détectée, surface manquante.",
                    missing=["Surface à peindre en m²."],
                    next_step="Indiquez par exemple : peinture 1600 m² deux couches.",
                )
        coats = 2
        cm = re.search(r"(\d+)\s*couches?", t)
        if cm:
            coats = int(cm.group(1))
        return calculate_paint(area_m, coats=coats)

    if kind == "plaster":
        if area_m is None:
            if pair:
                area_m = pair[0] * pair[1]
            elif nums:
                area_m = nums[0]
            else:
                return CalcResult(
                    kind="plaster", title="Calcul d'enduit",
                    understanding="Demande d'enduit détectée, surface manquante.",
                    missing=["Surface en m²."],
                    next_step="Indiquez par exemple : enduit 80 m² épaisseur 10 mm.",
                )
        th = 10.0
        tm = re.search(rf"(?:[ée]paisseur)\s*[:=]?\s*({_NUM})", t)
        if tm:
            th = parse_number(tm.group(1))
        return calculate_plaster(area_m, th, waste=max(waste, 0.10))

    if kind == "surface":
        if pair:
            return calculate_surface(pair[0], pair[1], extra_factor=_sides(t) if "face" in t else 1)
        if area_m is not None:
            result = CalcResult(
                kind="surface", title="Surface",
                understanding=f"Surface saisie : {area_m:g} m².",
                inputs={"area": area_m},
            )
            result.steps = [CalcStep("Surface", "valeur saisie", {"S": area_m}, area_m, "m²")]
            return result
        if len(nums) >= 2:
            return calculate_surface(nums[0], nums[1])
        return CalcResult(
            kind="surface", title="Calcul de surface",
            understanding="Demande de surface, dimensions manquantes.",
            missing=["Longueur et largeur/hauteur."],
            next_step="Indiquez par exemple : surface 12 x 2,5 m.",
        )
    return None
