"""Moteur de calcul BTP UniC Plaquiste.

Toutes les formules sont exposées. Aucun prix n'est inventé.
Les coefficients de déchet / entraxe sont des HYPOTHÈSES configurables
tant qu'ils n'ont pas été saisis dans la base UniC.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from typing import Any


STATUS_CONFIRMED = "confirmed"
STATUS_ESTIMATED = "estimated"
STATUS_ASSUMED = "assumed"
STATUS_MISSING = "missing"
STATUS_CALCULATED = "calculated"     # résultat d'une formule déterministe appliquée à des mesures confirmées (≠ la mesure elle-même)
STATUS_CONFLICTING = "conflicting"   # plusieurs sources se contredisent : jamais traité comme confirmé
ENGINE_VERSION = "2026.10.7"          # version du moteur : sert à comprendre un ancien devis après une évolution des formules

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
DOOR_STUDS = 3        # règle UniC : chaque porte prend 3 montants de renfort
# Fixations (pratique au Sénégal, valeurs supposées tant que le patron ne les a pas données : signalées « supposé ») :
ANCHOR_SPACING_M = 0.50   # une cheville à frapper tous les 0,50 m de rail (cloison) ou de cornière (plafond)
SCREWS9_PER_STUD = 4      # vis de 9 mm : 2 en tête + 2 en pied pour tenir chaque montant dans les rails
PACK = 100                # chevilles et vis vendues par paquet de 100 (comme les pivots et chevilles à laiton)
FIXINGS_DEFAULT = {"anchor_spacing_m": ANCHOR_SPACING_M, "anchors_per_pack": PACK, "screws9_per_stud": SCREWS9_PER_STUD,
                   "screws9_per_pack": PACK}


def fixings(given: dict | None = None) -> dict:
    """Valeurs de fixation : celles du patron (Réglages) quand il les a données, sinon les suppositions par défaut.
    `donne` dit lesquelles viennent du patron (statut confirmé) ; les autres restent « supposé »."""
    given = {k: v for k, v in (given or {}).items() if k in FIXINGS_DEFAULT and v not in (None, "", 0)}
    return {**FIXINGS_DEFAULT, **{k: float(v) if k == "anchor_spacing_m" else int(v) for k, v in given.items()}, "donne": sorted(given)}


def anchor_points(run_ml: float, runs: int = 1, spacing: float = ANCHOR_SPACING_M) -> int:
    """Chevilles à frapper le long d'un rail ou d'une cornière : une tous les `spacing` m, plus une au bout de chaque longueur."""
    return ceil_int(run_ml / spacing) + runs


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
    assumed_size: bool = False   # taille standard prise par défaut (non donnée par le patron)

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
            "verification": verify(self),
            "engine_version": ENGINE_VERSION,
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


def studs_needed(length_m: float, spacing_m: float, board_width_m: float | None = None) -> int:
    """Méthode UniC : chaque plaque (1,20 m) prend 3 montants (deux bords + milieu) ; deux plaques voisines partagent
    le montant de jonction → ⌈L / largeur plaque⌉ × (largeur / entraxe) + 1 (5 m → 5 plaques → 11 montants).
    Si l'entraxe ne divise pas la largeur de plaque : ⌈L / entraxe⌉ + 1 (un montant à chaque extrémité)."""
    if spacing_m <= 0:
        raise ValueError("Entraxe invalide")
    if board_width_m and board_width_m > 0:
        gaps = board_width_m / spacing_m
        if gaps >= 1 and abs(gaps - round(gaps)) < 1e-9:
            return math.ceil(length_m / board_width_m - 1e-9) * int(round(gaps)) + 1   # 1e-9 : 4,8 / 1,2 = 4,000…1
    return math.ceil(length_m / spacing_m - 1e-9) + 1


def stud_bars(n_studs: int, height_m: float, bar_m: float = BAR_LENGTH_M) -> int:
    """Barres de montant (2,90 m) : une par montant jusqu'à 2,90 m de haut ; au-delà, des rallonges taillées dans
    d'autres barres (chutes réutilisées). Recouvrement d'éclissage non compté."""
    if n_studs <= 0:
        return 0
    full = math.floor(height_m / bar_m + 1e-9)
    rest = round(height_m - full * bar_m, 6)
    if full == 0:
        return n_studs
    if rest <= 1e-6:
        return n_studs * full
    per_bar = max(1, math.floor(bar_m / rest + 1e-9))
    return n_studs * full + math.ceil(n_studs / per_bar)


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
        raise ValueError((f"Surface de {surface_m2:,.0f} m² : au-delà de {MAX_SURFACE_M2:,.0f} m² pour un seul calcul. "
                          "Vérifie les unités (m ou mm ?) puis confirme, ou découpe en plusieurs chantiers.").replace(",", " "))


def _fx_status(fx: dict, *keys: str) -> str:
    return STATUS_CONFIRMED if all(k in fx["donne"] for k in keys) else STATUS_ASSUMED


def _fx_text(fx: dict, support: str) -> str:
    told = "données par le patron" if len(fx["donne"]) == len(FIXINGS_DEFAULT) else \
        "supposées, à régler dans Réglages › Paramètres de calcul" if not fx["donne"] else "en partie supposées (Réglages)"
    return (f"Fixations ({told}) : 1 cheville à frapper tous les {fx['anchor_spacing_m']:g} m de {support}, paquets de "
            f"{fx['anchors_per_pack']}" + (f" ; {fx['screws9_per_stud']} vis de 9 mm par montant, paquets de {fx['screws9_per_pack']}"
                                           if support == "rail" else "") + ".")


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
    sides_known: bool = True,
    openings_known: bool | None = None,
    fixing_values: dict | None = None,
    walls: list[tuple[float, float]] | None = None,
) -> CalcResult:
    """`walls` : plusieurs cloisons (longueur, hauteur) de mêmes faces. Montants, rails et chevilles sont comptés cloison par
    cloison (chaque cloison a ses montants d'about) ; plaques et paquets une seule fois, sur le total ; ouvertures sur le total."""
    walls = [(float(w), float(h)) for w, h in walls] if walls else [(length_m, height_m)]
    multi = len(walls) > 1
    openings = openings or []
    if openings_known is None:
        openings_known = bool(openings)   # aucune ouverture citée ≠ « aucune ouverture » : à demander
    open_status = (STATUS_MISSING if not openings_known
                   else STATUS_ASSUMED if any(o.assumed_size for o in openings) else STATUS_CONFIRMED)
    one_face = sum(w * h for w, h in walls)
    check_inputs(positive={"longueur": min(w for w, _ in walls), "hauteur": min(h for _, h in walls), "largeur de plaque": board_width,
                           "hauteur de plaque": board_height, "entraxe": stud_spacing},
                 surface_m2=one_face * sides, waste=waste, confirmed_large=confirmed_large)
    b_area = board_area(board_width, board_height)
    # plusieurs cloisons : surface d'une face de toutes les cloisons (longueur × hauteur additionnées)
    areas = partition_area(one_face, 1.0, sides, openings) if multi else partition_area(length_m, height_m, sides, openings)
    n_boards = boards_needed(areas["net"], waste, b_area)
    wall_studs = [studs_needed(w, stud_spacing, board_width) for w, _ in walls]
    n_studs = sum(wall_studs)
    n_doors = sum(o.quantity for o in openings if o.kind == "door")
    door_studs = DOOR_STUDS * n_doors   # règle UniC : 3 montants de renfort par porte
    n_stud_bars = sum(stud_bars(n, h) for n, (_, h) in zip(wall_studs, walls)) + door_studs
    total_length = sum(w for w, _ in walls)
    tracks = tracks_length(total_length, 2)
    fx = fixings(fixing_values)
    anchors = sum(anchor_points(tracks_length(w, 2), 2, fx["anchor_spacing_m"]) for w, _ in walls)   # rail haut + rail bas
    screws9 = (n_studs + door_studs) * fx["screws9_per_stud"]
    # montants : un par montant, hauteur = hauteur cloison
    stud_ml = round_qty(sum(n * h for n, (_, h) in zip(wall_studs, walls)), 3)
    sizes = " + ".join(f"{w:g} × {h:g}" for w, h in walls)
    top = max(h for _, h in walls)
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
            (f"{len(walls)} cloisons ({sizes} m), " if multi else f"Cloison de {length_m:g} m de long × {height_m:g} m de haut, ")
            + f"{sides} face(s)"
            + (f", {len(openings)} ouverture(s)" if openings else "")
            + "."
        ),
        inputs={
            **({"walls": [[w, h] for w, h in walls]} if multi else {"length_m": length_m, "height_m": height_m}),
            "sides": sides,
            "openings": [asdict(o) for o in openings],
            "waste": waste,
            "board_width": board_width,
            "board_height": board_height,
            "stud_spacing": stud_spacing,
            "fixings": fixings(fixing_values),
        },
        next_step="Je peux transformer ces quantités en devis, bon de commande ou rapport.",
    )

    result.data_used = ([{"label": f"Cloison {i}", "value": f"{w:g} × {h:g}", "unit": "m", "status": STATUS_CONFIRMED}
                         for i, (w, h) in enumerate(walls, 1)] if multi else [
        {"label": "Longueur", "value": length_m, "unit": "m", "status": STATUS_CONFIRMED},
        {"label": "Hauteur", "value": height_m, "unit": "m", "status": STATUS_CONFIRMED},
    ]) + [
        {"label": "Faces", "value": sides, "unit": "", "status": STATUS_CONFIRMED if sides_known else STATUS_ASSUMED},
        {"label": "Ouvertures", "value": (f"{len(openings)} ({areas['openings']:g} m²)" if openings_known else "inconnues — à renseigner"),
         "unit": "", "status": open_status},
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
            "Σ longueur × hauteur des cloisons × faces" if multi else "longueur × hauteur × faces",
            {"cloisons": sizes, "faces": sides} if multi else {"longueur": length_m, "hauteur": height_m, "faces": sides},
            areas["gross"],
            "m²",
            STATUS_CALCULATED if sides_known else STATUS_ESTIMATED,
        ),
        CalcStep(
            "Surface des ouvertures",
            "Σ (largeur × hauteur × qté) × faces",
            {"ouvertures": [asdict(o) for o in openings], "faces": sides},
            areas["openings"] if openings_known else "inconnue",
            "m²",
            STATUS_CALCULATED if open_status == STATUS_CONFIRMED else open_status,
        ),
        CalcStep(
            "Surface nette" if openings_known else "Surface nette (sans déduction des ouvertures, inconnues)",
            "surface brute − ouvertures",
            {"brute": areas["gross"], "ouvertures": areas["openings"]},
            areas["net"],
            "m²",
            STATUS_CALCULATED if openings_known and open_status == STATUS_CONFIRMED and sides_known else STATUS_ESTIMATED,
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
            ("par cloison, " if multi else "") + "3 montants par plaque, jonctions partagées : ⌈ longueur / largeur plaque ⌉ × 2 + 1",
            {"longueur": [w for w, _ in walls] if multi else length_m, "largeur plaque": board_width, "entraxe": stud_spacing},
            n_studs,
            "u",
            STATUS_ESTIMATED,
        ),
        CalcStep(
            "Longueur de montants",
            "Σ montants × hauteur de leur cloison" if multi else "nombre de montants × hauteur",
            {"nombre": wall_studs, "hauteur": [h for _, h in walls]} if multi else {"nombre": n_studs, "hauteur": height_m},
            stud_ml,
            "ml",
            STATUS_ESTIMATED,
        ),
        CalcStep(
            "Rails (haut + bas)",
            "longueur × 2",
            {"longueur": round_qty(total_length, 3) if multi else length_m},
            tracks,
            "ml",
            STATUS_ESTIMATED,
        ),
    ]

    result.quantities = [
        QuantityLine(*board_sku(board_width, board_height), n_boards, "u",
                     "⌈Snette×(1+d)/Splaque⌉", STATUS_ESTIMATED),
        QuantityLine("MONTANT-M48", "Montant M48 (barre de 2,90 m)", n_stud_bars, "u",
                     "⌈L/largeur plaque⌉×2+1" + (" + rallonges" if n_stud_bars - door_studs != n_studs else "")
                     + (f" + 3 × {n_doors} porte(s)" if n_doors else ""), STATUS_ESTIMATED,
                     notes=f"{n_studs} montants, soit {stud_ml} ml " + ("à la hauteur de chaque cloison" if multi else f"à la hauteur {height_m:g} m")
                     + (f" ; hauteur > {BAR_LENGTH_M:g} m : rallonges (recouvrement d'éclissage non compté)"
                        if n_stud_bars - door_studs != n_studs else "")
                     + (f" ; + {door_studs} montants de renfort ({n_doors} porte(s) × 3)" if n_doors else "")),
        QuantityLine("UC-RAILS-48-MM", "Rails 48 mm (barre de 2,90 m, haut + bas)", ceil_int(tracks / BAR_LENGTH_M), "barre",
                     "⌈ L × 2 / 2,90 ⌉", STATUS_ESTIMATED),
        QuantityLine("VIS-PLAQUE", "Vis à plaque", screws, "u",
                     f"Snette×{DEFAULTS['screws_per_m2']:g}", STATUS_ASSUMED),
        # rails fixés au sol et au plafond par chevilles à frapper ; montants tenus dans les rails par vis de 9 mm
        QuantityLine("UC-PAQUET-CHEVILLES-A-FRAPPER", f"Chevilles à frapper (paquet de {fx['anchors_per_pack']})",
                     ceil_int(anchors / fx["anchors_per_pack"]), "paquet",
                     f"⌈ {anchors} chevilles (1 tous les {fx['anchor_spacing_m']:g} m de rail, {tracks:g} ml) / {fx['anchors_per_pack']} ⌉",
                     _fx_status(fx, "anchor_spacing_m", "anchors_per_pack")),
        QuantityLine("UC-VIS-9-MM", f"Vis 9 mm (paquet de {fx['screws9_per_pack']})", ceil_int(screws9 / fx["screws9_per_pack"]), "paquet",
                     f"⌈ {screws9} vis ({n_studs + door_studs} montants × {fx['screws9_per_stud']}) / {fx['screws9_per_pack']} ⌉",
                     _fx_status(fx, "screws9_per_stud", "screws9_per_pack")),
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
        f"Entraxe des montants = {stud_spacing:g} m : méthode UniC, chaque plaque prend 3 montants (bords + milieu), "
        "le montant de jonction est partagé entre deux plaques.",
        f"Vis = {DEFAULTS['screws_per_m2']:g} / m² (règle professionnelle par défaut).",
        "Portes : 3 montants de renfort par porte (règle UniC). Fenêtres : renforts non ajoutés automatiquement.",
        _fx_text(fx, "rail"),
        "Aucun prix n'est appliqué : les tarifs UniC ne sont pas inventés.",
    ]
    result.missing = [
        "Prix d'achat et de vente des matériaux (absents de la base UniC tant qu'ils n'ont pas été saisis).",
        "Main-d'œuvre : taux horaire non renseigné.",
        "Transport / livraison : non chiffré.",
    ]
    if not openings_known:
        result.missing.append("Ouvertures (portes, fenêtres) non déduites — non communiquées : quantités un peu surestimées.")
    if not sides_known:
        result.assumptions.append(f"Nombre de faces = {sides} (non précisé : à confirmer, la surface en dépend directement).")
    sized = [o for o in openings if o.assumed_size]
    if sized:
        result.assumptions.append("Taille d'ouverture standard prise par défaut : "
                                  + ", ".join(f"{o.kind} {o.width:g}×{o.height:g} m" for o in sized) + " (à confirmer).")
    result.notes = [
        "Les quantités de plaques et d'ossature sont des ESTIMATIONS arrondies à l'unité supérieure.",
    ]
    if multi:
        result.assumptions.insert(0, f"{len(walls)} cloisons ({sizes} m) : montants, rails et chevilles comptés cloison par cloison ; "
                                     "plaques et paquets sur le total ; ouvertures déduites du total.")
    if top > board_height + 1e-9:
        result.notes.append(f"Hauteur {top:g} m > plaque {board_height:g} m : raccords horizontaux et chutes à prévoir "
                            "(ou plaques plus longues).")
    else:
        result.notes.append("Vérifier la hauteur réelle des locaux : si H > hauteur de plaque, prévoir chutes / bandes de rive.")
    return result


def calculate_partition_from_area(
    area_m2: float,
    sides: int = 2,
    *,
    sides_known: bool = False,
    waste: float = DEFAULTS["waste"],
    board_width: float = DEFAULTS["board_width_m"],
    board_height: float = DEFAULTS["board_height_m"],
    include_finish: bool = True,
    confirmed_large: bool = False,
    fixing_values: dict | None = None,
) -> CalcResult:
    """Cloison dont seule la SURFACE est connue (« 200 m² de cloison ») : on calcule ce qui est déterminable (plaques, vis, bande, enduit,
    qui ne dépendent que de la surface) et on dit CLAIREMENT ce qui ne l'est pas (ossature : montants et rails demandent la longueur et la
    hauteur). Le résultat est marqué `partial` : aucun devis ni bon n'en est tiré sans demande explicite du patron."""
    check_inputs(positive={"surface": area_m2, "largeur de plaque": board_width, "hauteur de plaque": board_height},
                 surface_m2=area_m2 * sides, waste=waste, confirmed_large=confirmed_large)
    b_area = board_area(board_width, board_height)
    total = round_qty(area_m2 * sides, 3)
    n_boards = boards_needed(total, waste, b_area)
    screws = ceil_int(total * DEFAULTS["screws_per_m2"])
    tape = round_qty(total * DEFAULTS["tape_m_per_m2"], 2)
    compound = round_qty(total * DEFAULTS["compound_kg_per_m2_per_coat"] * DEFAULTS["compound_coats"], 2)
    result = CalcResult(
        kind="partition_area", title="Cloison : calcul partiel (surface seule)",
        understanding=f"Cloison de {area_m2:g} m² (une face), {sides} face(s) parementée(s) : calcul PARTIEL, surface seulement.",
        inputs={"area_m2": area_m2, "sides": sides, "waste": waste, "board_width": board_width, "board_height": board_height, "partial": True},
        next_step="Donne la longueur et la hauteur de la cloison, le nombre de faces et les ouvertures pour l'ossature et un devis complet.")
    result.data_used = [
        {"label": "Surface de cloison (une face)", "value": area_m2, "unit": "m²", "status": STATUS_CONFIRMED},
        {"label": "Faces", "value": sides, "unit": "", "status": STATUS_CONFIRMED if sides_known else STATUS_ASSUMED},
        {"label": "Ouvertures", "value": "inconnues — à renseigner", "unit": "", "status": STATUS_MISSING},
        {"label": "Longueur / hauteur", "value": "inconnues — à renseigner", "unit": "", "status": STATUS_MISSING},
        {"label": "Plaque", "value": f"{board_width:g} × {board_height:g}", "unit": "m", "status": STATUS_ASSUMED},
        {"label": "Déchet", "value": waste * 100, "unit": "%", "status": STATUS_ASSUMED},
    ]
    result.steps = [
        CalcStep("Surface totale à parementer", "surface × faces", {"surface": area_m2, "faces": sides}, total, "m²",
                 STATUS_CALCULATED if sides_known else STATUS_ESTIMATED),
        CalcStep("Nombre de plaques", "⌈ surface totale × (1 + déchet) / surface plaque ⌉",
                 {"totale": total, "dechet": waste, "plaque": b_area}, n_boards, "u", STATUS_ESTIMATED),
        CalcStep("Montants et rails", "dépend de la longueur et de la hauteur", {}, "non calculable", "", STATUS_MISSING),
    ]
    result.quantities = [
        QuantityLine(*board_sku(board_width, board_height), n_boards, "u", "⌈S×(1+d)/Splaque⌉", STATUS_ESTIMATED),
        QuantityLine("VIS-PLAQUE", "Vis à plaque", screws, "u", f"S×{DEFAULTS['screws_per_m2']:g}", STATUS_ASSUMED),
    ]
    if include_finish:
        result.quantities += [
            QuantityLine("BANDE-JOINT", "Bande à joint", tape, "ml", f"S×{DEFAULTS['tape_m_per_m2']:g}", STATUS_ASSUMED),
            QuantityLine("ENDUIT-JOINT", "Enduit à joint", compound, "kg",
                         f"S×{DEFAULTS['compound_kg_per_m2_per_coat']:g}×{DEFAULTS['compound_coats']}", STATUS_ASSUMED),
        ]
    result.assumptions = [
        f"Plaque standard BA13 {board_width:g} × {board_height:g} m = {b_area:.2f} m² (catalogue par défaut).",
        f"Déchet {waste*100:.0f} % (paramètre par défaut).",
        "« Surface de cloison » = une face ; multipliée par le nombre de faces.",
    ]
    if not sides_known:
        result.assumptions.append(f"Nombre de faces = {sides} (non précisé : à confirmer, la surface en dépend directement).")
    result.missing = [
        "Longueur et hauteur de la cloison : sans elles, montants et rails NE SONT PAS calculés.",
        "Ouvertures (portes, fenêtres) non déduites : quantités un peu surestimées.",
        "Type de cloison (simple/double ossature, épaisseur, hydrofuge ?) et format de plaque si différent du défaut.",
        "Prix d'achat et de vente (absents tant qu'ils n'ont pas été saisis) ; main-d'œuvre ; transport.",
    ]
    result.notes = ["CALCUL PARTIEL : seules les quantités qui dépendent de la surface sont données. Aucun devis complet n'est possible sans l'ossature."]
    # pour travailler tout de suite : ossature ESTIMÉE si la cloison fait 2,50 m de haut (hauteur des parois du chantier de
    # référence du patron). Donnée à part (notes), jamais dans les quantités : le devis attend la vraie longueur et la vraie hauteur.
    est_h = 2.5
    est_l = area_m2 / est_h
    est_studs = studs_needed(est_l, DEFAULTS["stud_spacing_m"], board_width)
    est_tracks = tracks_length(est_l, 2)
    fx = fixings(fixing_values)
    result.notes.append(
        f"Ossature ESTIMÉE si la cloison fait {est_h:g} m de haut (soit ≈ {est_l:.1f} m de long) : ≈ {est_studs} montants, "
        f"≈ {ceil_int(est_tracks / BAR_LENGTH_M)} barres de rail, "
        f"≈ {ceil_int(anchor_points(est_tracks, 2, fx['anchor_spacing_m']) / fx['anchors_per_pack'])} paquet(s) de chevilles à frapper, "
        f"≈ {ceil_int(est_studs * fx['screws9_per_stud'] / fx['screws9_per_pack'])} paquet(s) de vis 9 mm. "
        "À confirmer avec la longueur et la hauteur réelles.")
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
    dims_known: bool = True,
    include_finish: bool = True,
    fixing_values: dict | None = None,
    zones: list[tuple[float, float]] | None = None,
) -> CalcResult:
    """`zones` : plusieurs pièces, ou un plafond en L découpé en rectangles (longueur, largeur). Ossature, tiges et cornière sont
    comptées zone par zone (elles dépendent des côtés) ; plaques et paquets une seule fois, sur le total."""
    zones = [(float(a), float(b)) for a, b in zones] if zones else [(length_m, width_m)]
    multi = len(zones) > 1
    check_inputs(positive={"longueur": min(a for a, _ in zones), "largeur": min(b for _, b in zones),
                           "largeur de plaque": board_width, "hauteur de plaque": board_height},
                 surface_m2=sum(a * b for a, b in zones), waste=waste, confirmed_large=confirmed_large)
    area = round_qty(sum(a * b for a, b in zones), 3)
    b_area = board_area(board_width, board_height)
    n_boards = boards_needed(area, waste, b_area)
    # Fourrures parallèles à la longueur, espacées de 0,50 m sur la largeur ; tiges tous les 0,90 m sur chaque fourrure.
    # Sens de pose retenu : celui qui demande le moins de tiges (fourrures dans le sens le plus économique).
    f_sp, h_sp = DEFAULTS["furring_spacing_m"], DEFAULTS["hanger_spacing_m"]

    def layout(run: float, across: float) -> tuple[int, int, float]:
        rows_ = ceil_int(across / f_sp) + 1
        return rows_, rows_ * (ceil_int(run / h_sp) + 1), round_qty(run * rows_, 2)

    fx = fixings(fixing_values)
    rows = hangers = anchors = 0
    furring_ml = perimeter = 0.0
    for a, b in zones:
        z_rows, z_hangers, z_furring = min(layout(a, b), layout(b, a), key=lambda t: (t[1], t[2]))
        z_perimeter = round_qty(2 * (a + b), 2)
        rows, hangers, furring_ml, perimeter = rows + z_rows, hangers + z_hangers, furring_ml + z_furring, perimeter + z_perimeter
        anchors += anchor_points(z_perimeter, 4, fx["anchor_spacing_m"])   # cornière de rive : une longueur par mur
    furring_ml, perimeter = round_qty(furring_ml, 2), round_qty(perimeter, 2)
    sizes = " + ".join(f"{a:g} × {b:g}" for a, b in zones)
    screws = ceil_int(area * DEFAULTS["screws_per_m2"])
    tape = round_qty(area * DEFAULTS["tape_m_per_m2"], 2)
    compound = round_qty(area * DEFAULTS["compound_kg_per_m2_per_coat"] * DEFAULTS["compound_coats"], 2)

    result = CalcResult(
        kind="ceiling",
        title="Calcul de faux plafond",
        understanding=(f"Faux plafond en {len(zones)} zones ({sizes} m), {area:g} m², système {system}." if multi
                       else f"Faux plafond {length_m:g} × {width_m:g} m, système {system}."),
        inputs={
            **({"zones": [[a, b] for a, b in zones]} if multi else {"length_m": length_m, "width_m": width_m}),
            "waste": waste,
            "system": system,
            "fixings": fx,
        },
        next_step="Je peux préparer un devis quantité ou un bon de commande matériaux.",
    )
    dims_status = STATUS_CONFIRMED if dims_known else STATUS_ASSUMED
    result.data_used = ([{"label": f"Zone {i}", "value": f"{a:g} × {b:g}", "unit": "m", "status": dims_status}
                         for i, (a, b) in enumerate(zones, 1)] if multi else [
        {"label": "Longueur", "value": length_m, "unit": "m", "status": dims_status},
        {"label": "Largeur", "value": width_m, "unit": "m", "status": dims_status},
    ]) + [
        {"label": "Système", "value": system, "unit": "", "status": STATUS_ASSUMED},
        {"label": "Déchet", "value": waste * 100, "unit": "%", "status": STATUS_ASSUMED},
    ]
    each = "par zone, " if multi else ""
    result.steps = [
        CalcStep("Surface", "Σ longueur × largeur des zones" if multi else "longueur × largeur",
                 {"zones": sizes} if multi else {"longueur": length_m, "largeur": width_m}, area, "m²",
                 STATUS_CALCULATED if dims_known else STATUS_ESTIMATED),
        CalcStep("Nombre de plaques", "⌈ S × (1+d) / Splaque ⌉",
                 {"S": area, "d": waste, "Splaque": b_area}, n_boards, "u", STATUS_ESTIMATED),
        CalcStep("Lignes de fourrure (entraxe 0,50 m)", f"{each}⌈ côté / 0,50 ⌉ + 1", {"entraxe": f_sp}, rows, "u", STATUS_ESTIMATED),
        CalcStep("Points d'accroche (tige + pivot + cheville à laiton)",
                 f"{each}lignes × (⌈ longueur de fourrure / 0,90 ⌉ + 1)",
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
        # cornière de rive sur tout le périmètre : elle porte les bords des plaques contre les murs
        QuantityLine("UC-CORNIERES", "Cornière de rive (barre de 2,90 m)", ceil_int(perimeter / BAR_LENGTH_M), "barre",
                     f"⌈ périmètre {perimeter:g} ml / 2,90 ⌉", STATUS_ESTIMATED if dims_known else STATUS_ASSUMED),
        # la cornière de rive est fixée aux murs par des chevilles à frapper
        QuantityLine("UC-PAQUET-CHEVILLES-A-FRAPPER", f"Chevilles à frapper (paquet de {fx['anchors_per_pack']})",
                     ceil_int(anchors / fx["anchors_per_pack"]), "paquet",
                     f"⌈ {anchors} chevilles (1 tous les {fx['anchor_spacing_m']:g} m de cornière, {perimeter:g} ml) / {fx['anchors_per_pack']} ⌉",
                     _fx_status(fx, "anchor_spacing_m", "anchors_per_pack")),
    ]
    if include_finish:   # plaques vissées sous les fourrures, joints bandés et enduits : de quoi finir le plafond
        result.quantities += [
            QuantityLine("VIS-PLAQUE", "Vis à plaque", screws, "u", f"S×{DEFAULTS['screws_per_m2']:g}", STATUS_ASSUMED),
            QuantityLine("BANDE-JOINT", "Bande à joint", tape, "ml", f"S×{DEFAULTS['tape_m_per_m2']:g}", STATUS_ASSUMED),
            QuantityLine("ENDUIT-JOINT", "Enduit à joint", compound, "kg",
                         f"S×{DEFAULTS['compound_kg_per_m2_per_coat']:g}×{DEFAULTS['compound_coats']}", STATUS_ASSUMED),
        ]
    result.assumptions = [
        f"Système par défaut : plaques BA13 {board_width:g}×{board_height:g} m.",
        f"Déchet {waste*100:.0f} %.",
        "Méthode UniC : fourrures tous les 0,50 m, une tige tous les 0,90 m (tige + pivot + cheville à laiton), "
        "plaques de 2 m posées en travers des fourrures.",
        "Cornière de rive sur tout le périmètre (2 × (longueur + largeur)), fixée aux murs par chevilles à frapper ; "
        "entretoises non comptées.",
        _fx_text(fx, "cornière"),
        f"Finitions : {DEFAULTS['screws_per_m2']:g} vis à plaque / m², {DEFAULTS['tape_m_per_m2']:g} ml de bande / m², enduit "
        f"{DEFAULTS['compound_kg_per_m2_per_coat']:g} kg / m² × {DEFAULTS['compound_coats']} couches (règles par défaut).",
        "Aucun prix n'est appliqué.",
    ]
    result.missing = [
        "Type exact de faux plafond (BA13, dalles 600×600, démontable, acoustique) si différent du défaut.",
        "Hauteur de plénum (longueur des tiges).",
        "Prix UniC non renseignés.",
    ]
    if multi:
        result.assumptions.insert(0, f"{len(zones)} zones ({sizes} m) : fourrures, tiges et cornière comptées zone par zone ; "
                                     "plaques et paquets sur le total. Zones qui se touchent (plafond en L) : la cornière du côté "
                                     "commun est comptée en trop.")
    if not dims_known:
        result.assumptions.insert(0, ("Zone(s) dont seule la surface est connue, supposée(s) carrée(s)" if multi else
                                      f"Pièce supposée carrée ({length_m:.2f} × {width_m:.2f} m)")
                                  + " faute de longueur et largeur : fourrures et tiges sont approximatives. "
                                    "Donne les deux côtés pour un calcul exact.")
        result.missing.insert(0, "Longueur et largeur réelles du plafond (seule la surface est connue).")
    return result


MOULURE_BAR_M = 3.0          # règle du patron : moulures en barres de 3 m
MOULURE_BARS_PER_GLUE = 5    # règle du patron : 1 colle pour 5 barres, arrondi au-dessus


def moulure_lines(total_ml: float, taille: int = 4, colle: str = "silicone", *,
                  taille_known: bool = True) -> tuple[list[QuantityLine], list[CalcStep]]:
    """Barres et colles pour `total_ml` de moulure (règles du patron) : ⌈ longueur / 3 ⌉ barres, ⌈ barres / 5 ⌉ colles."""
    bars = ceil_int(total_ml / MOULURE_BAR_M)
    glue = ceil_int(bars / MOULURE_BARS_PER_GLUE)
    glue_sku, glue_name = ("UC-COLLE-A-POMPE", "Colle à pompe") if colle == "pompe" else ("UC-COLLE-SILICONE", "Colle silicone")
    lines = [QuantityLine(f"UC-MOULURE-TAILLE-{taille}-BARRE-DE-3-M", f"Moulure taille {taille} (barre de 3 m)", bars, "u",
                          f"⌈ {total_ml:g} ml / 3 ⌉", STATUS_ESTIMATED if taille_known else STATUS_ASSUMED),
             QuantityLine(glue_sku, glue_name, glue, "u", f"⌈ {bars} barres / 5 ⌉", STATUS_ESTIMATED)]
    steps = [CalcStep("Longueur de moulure", "tour des pièces (2 × (longueur + largeur)) ou longueur donnée", {"ml": total_ml},
                      round_qty(total_ml, 2), "ml", STATUS_CALCULATED),
             CalcStep("Barres de moulure (3 m)", "⌈ longueur / 3 ⌉", {"ml": total_ml}, bars, "u", STATUS_ESTIMATED),
             CalcStep("Colles", "⌈ barres / 5 ⌉", {"barres": bars}, glue, "u", STATUS_ESTIMATED)]
    return lines, steps


_MOULURE_RULE = ("Règle du patron : moulure en barres de 3 m, ⌈ longueur / 3 ⌉ barres ; 1 colle pour 5 barres "
                 "(silicone par défaut, à pompe si demandée).")


def add_moulure(result: CalcResult, total_ml: float, taille: int | None = None, colle: str = "silicone") -> CalcResult:
    """« faux plafond 5x4 avec moulure » : barres et colles ajoutées au calcul (le patron l'a demandé), sur le tour du plafond."""
    lines, steps = moulure_lines(total_ml, int(taille or 4), colle, taille_known=taille is not None)
    result.quantities += lines
    result.steps += steps
    result.inputs["moulure"] = {"length_ml": round_qty(total_ml, 3), "taille": int(taille or 4), "colle": colle}
    result.assumptions.append(_MOULURE_RULE + f" Moulure sur tout le tour : {total_ml:g} ml.")
    if taille is None:
        result.assumptions.append("Taille de moulure non précisée : taille 4 supposée (dis « taille 2 » sinon).")
    return result


def calculate_moulure(length_ml: float | None = None, *, rooms: list[tuple[float, float]] | None = None,
                      taille: int | None = None, colle: str = "silicone", rooms_known: bool = True) -> CalcResult:
    """Moulures de plafond, règles du patron : barres de 3 m (⌈ longueur / 3 ⌉), 1 colle pour 5 barres. Longueur donnée en ml,
    ou tour des pièces (2 × (longueur + largeur) chacune) : la moulure de plafond passe au-dessus des portes, rien n'est déduit."""
    rooms = [(float(a), float(b)) for a, b in rooms or []]
    total = round_qty(sum(2 * (a + b) for a, b in rooms) if rooms else float(length_ml or 0), 3)
    check_inputs(positive={"longueur de moulure": total})
    taille_known, taille = taille is not None, int(taille or 4)
    lines, steps = moulure_lines(total, taille, colle, taille_known=taille_known)
    sizes = " + ".join(f"{a:g} × {b:g}" for a, b in rooms)
    result = CalcResult(
        kind="moulure", title="Calcul de moulures",
        understanding=(f"Moulure taille {taille} autour de {len(rooms)} pièce(s) ({sizes} m) : {total:g} ml." if rooms
                       else f"Moulure taille {taille} sur {total:g} ml."),
        inputs={"length_ml": total, **({"rooms": [[a, b] for a, b in rooms]} if rooms else {}), "taille": taille, "colle": colle},
        next_step="Je peux l'ajouter à un devis si tu le demandes.")
    result.data_used = [
        {"label": "Longueur à couvrir", "value": total, "unit": "ml", "status": STATUS_CALCULATED if rooms else STATUS_CONFIRMED},
        {"label": "Taille de moulure", "value": taille, "unit": "", "status": STATUS_CONFIRMED if taille_known else STATUS_ASSUMED},
        {"label": "Colle", "value": "à pompe" if colle == "pompe" else "silicone", "unit": "", "status": STATUS_CONFIRMED},
    ]
    result.steps, result.quantities = steps, lines
    result.assumptions = [_MOULURE_RULE]
    if rooms:
        result.assumptions.append("Longueur = tour de chaque pièce, 2 × (longueur + largeur) ; la moulure passe au-dessus des portes : rien n'est déduit.")
    if not rooms_known:
        result.assumptions.append("Pièce(s) données par leur surface : supposées carrées pour le tour (donne les côtés pour un calcul exact).")
    if not taille_known:
        result.assumptions.append("Taille de moulure non précisée : taille 4 supposée (dis « taille 2 » sinon).")
        result.missing.append("Taille de moulure (2 ou 4).")
    result.notes = ["Coupes d'onglet dans les angles : prises dans l'arrondi des barres."]
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
                 area, "m²", STATUS_CALCULATED),
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


_WORD_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "trente": 30,
    "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100,
}
_WORD_NUM = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
# nombres composés dits à voix haute : « dix-huit », « soixante-dix », « quatre-vingt-quinze », « vingt et un », « deux cent cinquante »
_S = r"[\s-]+"
_U = r"(?:un|une|deux|trois|quatre|cinq|six|sept|huit|neuf)"
_TEEN = rf"(?:dix{_S}(?:sept|huit|neuf)|onze|douze|treize|quatorze|quinze|seize|dix)"
_TENS = (rf"(?:quatre{_S}vingts?(?:{_S}(?:{_TEEN}|{_U}))?|soixante(?:{_S}et{_S}onze|{_S}(?:{_TEEN}|{_U}))?"
         rf"|(?:vingt|trente|quarante|cinquante)(?:{_S}et{_S}(?:un|une)|{_S}(?:deux|trois|quatre|cinq|six|sept|huit|neuf))?)")
_SPOKEN = rf"(?:(?:(?:deux|trois|quatre|cinq|six|sept|huit|neuf){_S})?cents?(?:{_S}(?:{_TENS}|{_TEEN}|{_U}))?|{_TENS}|{_TEEN}|{_U})"


def spoken_number(phrase: str) -> int:
    """« soixante-dix-huit » → 78 ; « quatre-vingt-dix » → 90 ; « deux cent cinquante » → 250 (phrase déjà reconnue par _SPOKEN)."""
    total = 0
    for tok in (w for w in re.split(r"[\s-]+", phrase.strip()) if w and w != "et"):
        if tok in ("cent", "cents"):
            total = (total or 1) * 100 if total < 100 else total + 100
        elif tok in ("vingt", "vingts") and total % 100 == 4:
            total += 76   # quatre-vingt : 4 → 80
        else:
            total += _WORD_NUMBERS[tok] if tok in _WORD_NUMBERS else {"dix": 10}[tok]
    return total


# Mots du métier tapés vite ou dictés : fautes, abréviations SMS. Seuls les mots ci-dessous sont touchés (jamais un mot juste).
_TYPOS = {
    "devi": "devis", "devie": "devis", "devit": "devis", "dvis": "devis", "dvs": "devis",
    "factur": "facture", "facure": "facture", "facturre": "facture", "factre": "facture", "fature": "facture", "fact": "facture",
    "plafon": "plafond", "plafont": "plafond", "plaffond": "plafond", "plaphond": "plafond", "plafonf": "plafond", "plafons": "plafonds",
    "cloisson": "cloison", "cloissons": "cloisons", "cloisonn": "cloison", "kloison": "cloison", "cloizon": "cloison", "cloisone": "cloison",
    "clwazon": "cloison", "closon": "cloison",
    "peintur": "peinture", "peinteure": "peinture", "painture": "peinture", "pinture": "peinture", "peintture": "peinture",
    "plako": "placo", "placau": "placo", "plaquo": "placo", "plakos": "placo",
    "anduit": "enduit", "enduie": "enduit", "enduix": "enduit", "enduis": "enduit",
    "montan": "montant", "montans": "montants", "fourure": "fourrure", "fourures": "fourrures", "corniere": "cornière",
    "longeur": "longueur", "largueur": "largeur", "hauteure": "hauteur", "hotteur": "hauteur", "otteur": "hauteur",
    "pr": "pour", "ds": "dans", "avc": "avec", "cmb": "combien", "cb": "combien", "qte": "quantité", "qté": "quantité",
}
_TYPO_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _TYPOS), key=len, reverse=True)) + r")\b")


def fix_typos(text: str) -> str:
    """« fai le devi d'une cloisson de 4 mettre pr moussa » → « … devis d'une cloison de 4 mètres pour moussa » : le sens du patron,
    pas son orthographe. Texte en minuscules ; les noms propres et les mots justes ne changent pas."""
    t = _TYPO_RE.sub(lambda m: _TYPOS[m.group(1)], text)
    t = re.sub(r"\bfau[tx]?\s*-?\s*plafond", "faux plafond", t)                     # « faut plafond », « fauxplafond »
    t = re.sub(r"(\d)\s*mett?res?\b", r"\1 mètres", t)                                # « 4 mettre », « 3metres »
    return t


def normalize_dimensions(text: str) -> str:
    """Écritures françaises des mesures ramenées à une forme simple AVANT tout calcul (sinon « 4m50 sur 2m60 » se lisait
    50 × 2 m) : « 4m50 » → 4.50 m ; « 3 mètres 20 » → 3.20 m ; « 2 mètres et demi » → 2.5 m ; « mètres carrés » → m² ;
    nombres en lettres collés à une mesure (« cinq mètres sur quatre ») → chiffres. « 6 mètres 2 portes » reste 6 m + 2 portes.
    Fautes courantes d'abord (fix_typos) : « cloisson », « plafon », « 4 mettre »."""
    t = fix_typos(text.lower().replace("\u00a0", " "))
    t = re.sub(r"\bm[eè]tres?\s+carr[eé]s?\b|\bm\s+carr[eé]s?\b", "m²", t)
    # nombres en lettres (composés compris : « dix-huit », « soixante-dix »), seulement près d'une mesure (« un plafond » reste tel quel)
    spoken = lambda m: str(spoken_number(m.group(1)))   # noqa: E731
    t = re.sub(rf"\b({_SPOKEN})\b(?=\s*(?:m\b|m²|ml\b|cm\b|m[eè]tres?\b|virgule\b|et\s+demi|sur\b|par\b|x\b))", spoken, t)
    t = re.sub(rf"(?:(?<=\bsur\s)|(?<=\bpar\s)|(?<=\bx\s))({_SPOKEN})\b", spoken, t)
    # après « mètres » ou « virgule » : la suite de la mesure (« deux mètres soixante » = 2,60 m ; avant : 2 m, « soixante » perdu)
    t = re.sub(rf"(?:(?<=m[eè]tres\s)|(?<=m[eè]tre\s)|(?<=virgule\s))({_SPOKEN})\b", spoken, t)
    t = re.sub(r"\b(\d+)\s+virgule\s+(\d+)\b", r"\1.\2", t)                                   # « deux virgule cinq »
    t = re.sub(r"\b(\d+)\s?m(\d{2})\b(?![.,]?\d)", r"\1.\2 m", t)                                 # 4m50, 2m05 (« 20 m2 » = m²)
    t = re.sub(r"\b(\d+)\s*m[eè]tres?\s+(\d{1,2})\b(?!\s*(?:portes?|fen[eê]tres?|faces?|plaques?|cm|mm|m\b|m[eè]tres?|[.,]\d))",
               r"\1.\2 m", t)                                                                      # 3 mètres 20
    t = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*(m\b|m[eè]tres?)?\s*et\s+demi\b",
               lambda m: f"{parse_number(m.group(1)) + 0.5:g}" + (" m" if m.group(2) else ""), t)      # 2 mètres et demi
    return t


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
    """Faces habillées. « simple face », « une seule face », « d'un côté » et un DOUBLAGE (contre un mur) = 1 face ; sinon 2
    (avant, seuls « une face » / « simple peau » donnaient 1 : les autres phrases doublaient les plaques du devis)."""
    t = text.lower()
    if re.search(r"deux\s+faces|2\s+faces|double\s+face|both\s+sides|double\s+peau|des\s+deux\s+c[oô]t[eé]s|2\s+c[oô]t[eé]s|des deux", t):
        return 2
    if re.search(r"une\s+(?:seule\s+)?face|1\s+face|simple\s+face|simple\s+peau|one\s+side|"
                 r"(?:sur\s+|d'|d’)?un\s+(?:seul\s+)?c[oô]t[eé]|1\s+c[oô]t[eé]|doublage", t):
        return 1
    return 2


_COUNT_WORDS = {"une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6}
_COUNT = r"(\d+|une|un|deux|trois|quatre|cinq|six)"


def _count(raw: str) -> int:
    return int(raw) if raw.isdigit() else _COUNT_WORDS[raw]


def _size(raw: str) -> float:
    v = parse_number(raw)
    return v / 100 if v > 10 else v   # « porte de 90 sur 210 » : centimètres


def _openings(text: str) -> list[Opening]:
    """Portes et fenêtres : « 2 portes », « deux portes de 0,90 sur 2,10 », « porte 0.90 m x 2.10 m », « fenêtre de 120 par 100 ».
    Une taille donnée est gardée avec son nombre (avant : « deux portes de 0,90 sur 2,10 » = 1 porte de taille supposée)."""
    t = text.lower()
    openings: list[Opening] = []
    size = r"(\d+(?:[.,]\d+)?)\s*(?:m\b)?\s*(?:x|×|sur|par)\s*(\d+(?:[.,]\d+)?)"
    door_w = r"(?:portes?|doors?)(?:\s+(?:standard|simple|double|pleine|isoplane|int[ée]rieure|vitr[ée]e))?"
    window_w = r"(?:fen[eê]tres?|windows?|baies?(?:\s+vitr[ée]es?)?)"   # baie vitrée : une ouverture sans renfort de porte
    for kind, word in (("door", door_w), ("window", window_w)):
        for m in re.finditer(rf"(?:\b{_COUNT}\s+)?{word}\s+(?:de\s+|d'|d’)?{size}", t):
            n = _count(m.group(1)) if m.group(1) else 1
            openings.append(Opening(kind, _size(m.group(2)), _size(m.group(3)), n))
    # « 2 portes » ; « avec porte », « et fenêtre » sans nombre = une
    door_q = re.search(rf"\b{_COUNT}\s*(?:portes?|doors?)\b|\b(?P<one>avec|et|plus)\s+(?:la\s+)?portes?\b", t)
    win_q = re.search(rf"\b{_COUNT}\s*(?:fen[eê]tres?|windows?|baies?)\b|\b(?P<one>avec|et|plus)\s+(?:la\s+|une\s+)?(?:fen[eê]tres?|baies?)\b", t)
    if door_q and not any(o.kind == "door" for o in openings):
        openings.append(Opening("door", 0.90, 2.04, 1 if door_q.group("one") else _count(door_q.group(1)), assumed_size=True))
    if win_q and not any(o.kind == "window" for o in openings):
        openings.append(Opening("window", 1.20, 1.20, 1 if win_q.group("one") else _count(win_q.group(1)), assumed_size=True))
    return openings


_ROOM = (r"(?:pi[eè]ces?|chambres?|salles?|salons?|s[ée]jours?|cuisines?|bureaux?|couloirs?|halls?|magasins?|boutiques?|"
         r"toilettes?|wc|douches?|garages?|zones?|parties?|cloisons?|murs?|plafonds?|appartements?|villas?|rooms?|walls?)")
_ZONE = re.compile(rf"(?P<a>{_NUM})\s*(?:m|ml|mètres?|metres?)?\s*(?:[x/]|sur|par)\s*(?P<b>{_NUM})(?:\s*(?:m|ml)\b)?"
                   rf"|(?P<s>{_NUM})\s*(?:m²|m2)|(?P<l>{_NUM})\s*m\b(?!\s*(?:de\s+)?haut(?:eur)?\b(?![\s:=]*\d))")
_PART_WORD = re.compile(r"(?:(?P<open>portes?|fen[eê]tres?|baies?|trappes?|ouvertures?|spots?|doors?|windows?)|(?P<mat>dalles?|plaques?))"
                        r"\b[^\d]{0,15}$")


def _is_part(before: str, a: float, b: float) -> bool:
    """Taille d'une porte, d'une fenêtre, d'une trappe, d'une dalle ou d'une plaque : pas une pièce ni une cloison. Après « dalles » ou
    « plaques », seulement une taille de plaque (« plaques 1200 x 2500 », « dalles 60x60 ») : « en plaques 5x4 » reste la pièce."""
    m = _PART_WORD.search(before)
    if not m or re.search(rf"\b{_ROOM}\b", m.group(0)):   # « plaques salon 5x4 » : la mesure est celle du salon
        return False
    return bool(m.group("open")) or (a <= 2.6 and b <= 2.6) or (a >= 30 and b >= 30)


def _zones(t: str) -> list[tuple[str, Any, int]]:
    """Mesures de la phrase dans l'ordre, chacune avec son nombre : (« pair », (a, b), n), (« area », m², n), (« length », m, n).
    « 3 chambres de 4x4 » = 3 × (4, 4) ; « salon 5x4 et chambre 4x3 » = deux zones. Une longueur seule ne compte que comptée
    (« 2 cloisons de 4 m ») ou additionnée (« 3 m + 4 m », « 3 m et 4 m »). Les tailles de porte, fenêtre, trappe, dalle ou plaque ne sont pas
    des zones ; « 5x4 soit 20 m² » ne compte qu'une fois."""
    out: list[tuple[str, Any, int]] = []
    for m in _ZONE.finditer(t):
        before = t[max(0, m.start() - 40):m.start()]
        if m.group("a") and _is_part(before, parse_number(m.group("a")), parse_number(m.group("b"))):
            continue
        cm = re.search(rf"\b{_COUNT}\s+{_ROOM}\b(?:(?!\bet\b)[^\d,;+]){{0,25}}$", before)
        n = _count(cm.group(1)) if cm else 1
        if m.group("a"):
            out.append(("pair", (parse_number(m.group("a")), parse_number(m.group("b"))), n))
        elif m.group("s"):
            out.append(("area", parse_number(m.group("s")), n))
        elif re.search(r"haut(?:eur)?\s*(?:de\s*|:\s*)?$", before):
            continue   # « hauteur 2,5 m » : pas une cloison de plus
        elif cm or re.search(r"(?:\+|\bet)\s*$", before) or re.match(rf"\s*(?:\+|et\s+{_NUM}\s*m\b)", t[m.end():]):
            out.append(("length", parse_number(m.group("l")), n))
    pairs = [v[0] * v[1] for k, v, _ in out if k == "pair"]
    return [z for z in out if not (z[0] == "area" and any(abs(z[1] - p) <= 0.01 * p for p in pairs))]


def _no_openings(text: str) -> bool | None:
    """« sans ouverture », « ni porte ni fenêtre », « aucune ouverture » : rien à déduire, et c'est su (plus « à renseigner »)."""
    t = text.lower()
    if re.search(r"sans\s+(?:aucune\s+)?ouvertures?|aucune\s+(?:ouverture|porte\s+ni\s+fen[eê]tre)|pas\s+d['’]\s*ouvertures?|"
                 r"(?:sans|ni)\s+portes?\s+ni\s+fen[eê]tres?", t):
        return True
    return None


def detect_calc_kind(text: str) -> str | None:
    t = normalize_dimensions(text)   # « 100 mètres carrés » = « 100 m² » : même ouvrage à préciser
    if re.search(r"moulures?|corniches?", t) and not re.search(r"faux[\s-]?plafond|plafond suspendu|cloison|doublage|ba ?13|placo|plaques?", t):
        return "moulure"   # « moulure salon 5x4 » : des barres et de la colle, pas un faux plafond    if re.search(r"faux[\s-]?plafond|suspended ceiling|plafond suspendu", t):
        return "ceiling"
    if re.search(r"peinture|paint|peintur|\b(?:re)?peind|\bpeins\b", t):   # « peindre 60 m² » : de la peinture, pas « plafond ou cloison ? »
        return "paint"
    if re.search(r"plafond", t) and not re.search(r"cloison|doublage", t):
        return "ceiling"
    if re.search(r"enduit|pl[aâ]tre(?!rie)|plaster(?!board)|ratissage|lissage", t) and not re.search(
        r"plaque|placo|ba13|cloison", t
    ):
        return "plaster"
    if re.search(r"cloison|drywall|partition|doublage|montant|rail|\bmurs?\b", t):
        return "partition"
    # « 100 m² de BA13 », « j'ai une surface de 100 m² » : plafond OU cloison ? Les deux ouvrages n'ont pas la même ossature
    # (plafond : tiges, pivots, fourrures, cornières ; cloison : rails, montants) : on ne suppose JAMAIS la cloison.
    area_only = re.search(r"\d\s*(?:m²|m2)\b", t) and not re.search(r"\d\s*(?:m\b)?\s*[x×]\s*\d", t)
    if re.search(r"plaqu|placo|ba13|ba 13|ossature", t) or (area_only and not re.search(r"combien de plaques|how many boards", t)):
        return "a_preciser"
    if re.search(r"surface|superficie|aire|m²|m2|combien de plaques|how many boards", t):
        return "surface"
    return None


_UNITLESS = re.compile(r"(?<![\d.,])(\d{3}|\d{4})\s*(x|×|sur|par)\s*(\d{3}|\d{4})(?![\d.,]|\s*(?:m|cm|mm|ml|m²|m2)\b)", re.I)


def _unitless_to_m(text: str) -> tuple[str, list[str]]:
    """« 450 x 350 » sans unité : en mètres ce serait 157 500 m² (impossible) ; un plaquiste parle en centimètres (3 chiffres)
    ou en millimètres (4 chiffres). Converti et signalé ; les tailles de porte, dalle ou plaque ne sont pas touchées."""
    seen: list[str] = []

    def conv(m: re.Match) -> str:
        a, b = m.group(1), m.group(3)
        if len(a) != len(b) or _is_part(text[max(0, m.start() - 40):m.start()].lower(), int(a), int(b)):
            return m.group(0)
        div = 100 if len(a) == 3 else 1000
        seen.append(f"{a} × {b} lu en {'centimètres' if div == 100 else 'millimètres'} : {int(a) / div:g} × {int(b) / div:g} m")
        return f"{int(a) / div:g} x {int(b) / div:g} m"
    return _UNITLESS.sub(conv, text), seen


def _plenum(t: str) -> float | None:
    """Hauteur de suspente (plénum), en m : « plénum de 40 cm », « à 30 cm sous la dalle », « descente 0,5 m »."""
    m = re.search(rf"(?:pl[ée]num|descente|suspentes?|retomb[ée]e)\s*(?:de\s*|:\s*)?({_NUM})\s*(cm|mm|m)\b"
                  rf"|({_NUM})\s*(cm|mm|m)\s*sous\s*(?:la\s*)?dalle", t.lower())
    if not m:
        return None
    v = parse_number(m.group(1) or m.group(3)) / {"cm": 100, "mm": 1000, "m": 1}[m.group(2) or m.group(4)]
    return v if 0 < v <= 3 else None


def calculate_from_text(text: str, defaults: dict | None = None) -> CalcResult | None:
    """Calcul à partir d'une phrase. Refuse les dimensions négatives ; signale les valeurs en trop au lieu de les ignorer."""
    text, unitless = _unitless_to_m(normalize_dimensions(text))
    t = text.lower().replace("×", "x")
    if re.search(r"(?<![\w.,])-\d", t):
        raise ValueError("Dimension négative détectée : donnez des longueurs positives.")
    result = _calculate_from_text(text, defaults)
    if result is not None and unitless:
        result.assumptions.insert(0, "Cotes sans unité : " + " ; ".join(unitless) + " (à confirmer).")
    if result is not None and result.kind == "ceiling" and result.quantities and re.search(r"moulures?|corniches?", t):
        zs = result.inputs.get("zones") or [[result.inputs["length_m"], result.inputs["width_m"]]]
        add_moulure(result, sum(2 * (a + b) for a, b in zs), _moulure_size(t), _glue(t))
    plenum = _plenum(text) if result is not None and result.kind == "ceiling" and result.quantities else None
    if plenum:   # donné par le patron : plus « manquant » ; les tiges doivent couvrir cette hauteur
        result.inputs["plenum_m"] = plenum
        result.data_used.insert(-2, {"label": "Plénum (hauteur de suspente)", "value": plenum, "unit": "m", "status": STATUS_CONFIRMED})
        result.missing = [m for m in result.missing if not m.startswith("Hauteur de plénum")]
        result.assumptions.append(f"Tiges d'au moins {plenum:g} m (plénum donné) + la marge de réglage du pivot.")
    extra = re.search(rf"({_NUM})\s*m?\s*x\s*({_NUM})\s*m?\s*x\s*({_NUM})", t)
    if result is not None and extra:
        result.missing.append(
            f"Trois valeurs reçues ({extra.group(1)} × {extra.group(2)} × {extra.group(3)}) : seules les deux premières sont utilisées. "
            "Précisez ce que représente la troisième (hauteur, nombre, épaisseur).")
    return result


def _moulure_size(t: str) -> int | None:
    m = re.search(r"taille\s*(\d)\b", t)
    return int(m.group(1)) if m else None


def _glue(t: str) -> str:
    return "pompe" if re.search(r"colle\s+(?:[àa]\s+)?pompe|\bpompe\b", t) else "silicone"


def _calculate_zones(kind: str, zones: list[tuple[str, Any, int]], t: str, cfg: dict, waste: float,
                     height: float | None) -> CalcResult | None:
    """Plusieurs pièces ou cloisons dans la même phrase (« salon 5x4 et chambre 4x3 », « 2 cloisons de 3 x 2,5 », plafond en L) :
    un seul calcul pour le tout. Avant, seule la première mesure était comptée et le reste disparaissait du devis."""
    if kind == "ceiling":
        rects, guessed = [], False
        for k, v, n in zones:
            if k == "pair":
                rects += [v] * n
            elif k == "area":   # pièce donnée par sa surface : supposée carrée (signalé)
                rects += [(math.sqrt(v), math.sqrt(v))] * n
                guessed = True
        return calculate_ceiling(*rects[0], zones=rects, waste=waste, board_width=cfg["board_width_m"], board_height=cfg["board_height_m"],
                                 dims_known=not guessed, fixing_values=cfg.get("fixings")) if rects else None
    walls, areas, assumed_h = [], [], False
    for k, v, n in zones:
        if k == "pair":
            L, H = v
            if (H > 6 and L <= 6) or (L < H and L <= 4.5 and H > 6):
                L, H = H, L   # « 2,5 x 4 » : hauteur et longueur inversées
            walls += [(L, H)] * n
        elif k == "length":
            walls += [(v, height or 2.5)] * n
            assumed_h = assumed_h or height is None
        else:
            areas += [v] * n
    if not walls:
        return None
    if any(H > 8 or L > 2000 for L, H in walls):
        return CalcResult(kind="partition", title="Calcul de cloison",
                          understanding="Dimensions peu crédibles (" + " + ".join(f"{L:g} x {H:g}" for L, H in walls) + " m) : "
                                        "je préfère ne pas calculer.",
                          missing=["Longueur et hauteur de chaque cloison en mètres."],
                          next_step="Indiquez par exemple : 2 cloisons de 4 x 2,5 m.")
    res = calculate_partition(*walls[0], sides=_sides(t), openings=_openings(t), openings_known=_no_openings(t), walls=walls, waste=waste,
                              board_width=cfg["board_width_m"], board_height=cfg["board_height_m"],
                              stud_spacing=cfg["stud_spacing_m"], fixing_values=cfg.get("fixings"))
    if assumed_h:
        res.assumptions.insert(0, "Hauteur non donnée : 2,50 m supposée (à confirmer, plaques et montants en dépendent).")
        res.missing.insert(0, "Hauteur des cloisons.")
    if areas:
        res.missing.insert(0, "Surface(s) " + " + ".join(f"{a:g} m²" for a in areas) + " NON comptée(s) : donne la longueur et la "
                              "hauteur de ces cloisons.")
    return res


def _calculate_from_text(text: str, defaults: dict | None = None) -> CalcResult | None:
    cfg = {**DEFAULTS, **(defaults or {})}
    kind = detect_calc_kind(text)
    if kind is None:
        return None
    t = text.lower().replace("×", "x")
    if re.search(r"plaques?\s*(?:de\s*)?(?:2[.,]50?|2500)\b", t):
        cfg["board_height_m"] = 2.5   # seulement si le patron le précise : la plaque par défaut fait 2 m
    t = re.sub(r"\b(?:ba|bs)\s?\d{1,2}\b", " ", t)  # références produit (BA13, BA 18) : pas des dimensions
    def to_m(raw: str, unit: str, first: bool = False) -> str:
        v, div = parse_number(raw), (1000 if unit == "mm" else 100)
        return f"{v:g}" if first and v / div < 0.1 else f"{v / div:g}"   # « 4,5 x 350 cm » : 4,5 est déjà en mètres
    t = re.sub(rf"({_NUM})\s*(?:x|sur|par)\s*({_NUM})\s*(mm|cm)\b",
               lambda m: f"{to_m(m.group(1), m.group(3), True)} x {to_m(m.group(2), m.group(3))} m", t)   # 400 x 350 cm : les DEUX cotes
    t = re.sub(rf"({_NUM})\s*(mm|cm)\b",
               lambda m: f"{parse_number(m.group(1)) / (1000 if m.group(2) == 'mm' else 100):g} m", t)   # 3500 mm → 3.5 m

    zones = _zones(t) if kind in ("ceiling", "partition", "moulure") else []
    # plafond / cloison : la première vraie mesure (pas « plaques 1200 x 2500 » ni « porte de 0,9 x 2,1 », qui ne sont pas l'ouvrage)
    pair = next((v for k, v, _ in zones if k == "pair"), None) if kind in ("ceiling", "partition", "moulure") else _extract_dimension_pair(t)
    # « 2 portes », « 3 chambres », « 2 couches » : des nombres d'objets, pas des cotes (avant : « cloison 12 m, 2 portes » = 2 m de haut)
    parts = lambda m: " " if _is_part(t[max(0, m.start() - 40):m.start()], parse_number(m.group(1)), parse_number(m.group(2))) else m.group(0)   # noqa: E731
    nums = _find_numbers(re.sub(rf"\b\d+\s+(?:{_ROOM}|portes?|fen[eê]tres?|faces?|c[oô]t[eé]s?|couches?|spots?|trappes?)\b", " ",
                                re.sub(rf"({_NUM})\s*(?:m\b)?\s*(?:x|sur|par)\s*({_NUM})", parts, t)))
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

    if kind in ("ceiling", "partition") and sum(n for k, _, n in zones if kind == "partition" or k != "length") > 1:
        several = _calculate_zones(kind, zones, t, cfg, waste, parse_number(height.group(1)) if height else None)
        if several is not None:
            return several

    if kind == "partition":
        L = H = None
        if area_m is not None and not pair and not length:   # « cloison de 20 m² » : une surface, pas 20 m × 2 m (le 2 de « m2 »)
            sides, sides_known = _sides(t), bool(re.search(r"faces?|c[oô]t[eé]s?|peau|doublage|sides?", t))
            if not height:
                return calculate_partition_from_area(area_m, sides, sides_known=sides_known, waste=waste, board_width=cfg["board_width_m"],
                                                     board_height=cfg["board_height_m"], fixing_values=cfg.get("fixings"))
            H = parse_number(height.group(1))
            res = calculate_partition(round_qty(area_m / H, 3), H, sides=sides, openings=_openings(t), openings_known=_no_openings(t), waste=waste,
                                      board_width=cfg["board_width_m"], board_height=cfg["board_height_m"],
                                      stud_spacing=cfg["stud_spacing_m"], fixing_values=cfg.get("fixings"), sides_known=sides_known)
            res.assumptions.insert(0, f"Longueur déduite : {area_m:g} m² (une face) / {H:g} m de haut = {area_m / H:.2f} m, "
                                      "en une seule cloison (plusieurs cloisons : donne leurs longueurs).")
            return res
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
        h_assumed = H is None and len(nums) < 2
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
        res = calculate_partition(
            L, H, sides=_sides(t), openings=_openings(t), openings_known=_no_openings(t), waste=waste,
            board_width=cfg["board_width_m"], board_height=cfg["board_height_m"],
            stud_spacing=cfg["stud_spacing_m"], fixing_values=cfg.get("fixings"),
        )
        if h_assumed:   # hauteur non dite : supposée, et dite comme telle (avant : affichée « confirmée »)
            for d in res.data_used:
                if d["label"] == "Hauteur":
                    d["status"] = STATUS_ASSUMED
            res.assumptions.insert(0, "Hauteur non donnée : 2,50 m supposée (à confirmer, plaques et montants en dépendent).")
            res.missing.insert(0, "Hauteur de la cloison.")
        return res

    if kind == "ceiling":
        square_from_area = None
        if pair:
            a, b = pair
        elif length and width:
            a, b = parse_number(length.group(1)), parse_number(width.group(1))
        elif area_m is not None:
            side = math.sqrt(area_m)
            a, b = round(side, 3), round(area_m / side, 3)
            square_from_area = area_m
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
                                 board_height=cfg["board_height_m"], dims_known=square_from_area is None,
                                 fixing_values=cfg.get("fixings"))

    if kind == "moulure":
        rooms, guessed = [], False
        for k, v, n in zones:
            if k == "pair":
                rooms += [v] * n
            elif k == "area":   # pièce donnée par sa surface : supposée carrée
                rooms += [(math.sqrt(v), math.sqrt(v))] * n
                guessed = True
        ml = re.search(rf"({_NUM})\s*(?:ml\b|m(?:[eè]tres?)?\s+lin[ée]aires?)", t) or (None if rooms else re.search(rf"({_NUM})\s*(?:m|m[eè]tres?)\b", t))
        if not rooms and not ml:
            return CalcResult(kind="moulure", title="Calcul de moulures", understanding="Moulure demandée, longueur manquante.",
                              missing=["Longueur à couvrir en ml, ou les dimensions de la pièce."],
                              next_step="Indiquez par exemple : moulure salon 5 x 4, ou moulure 18 ml taille 2.")
        return calculate_moulure(None if rooms else parse_number(ml.group(1)), rooms=rooms or None, taille=_moulure_size(t),
                                 colle=_glue(t), rooms_known=not guessed)

    if kind == "paint":
        from_pair = False
        if area_m is None:
            if pair:
                area_m = pair[0] * pair[1]
                from_pair = True
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
        words = {"une": 1, "un": 1, "simple": 1, "deux": 2, "double": 2, "trois": 3, "quatre": 4}
        cm = re.search(r"(\d+|une|un|simple|deux|double|trois|quatre)\s*couches?", t)
        if cm:
            coats = int(cm.group(1)) if cm.group(1).isdigit() else words[cm.group(1)]
        note = None
        rooms = re.search(r"\bmurs?\b|pi[eè]ce|salon|chambre|cuisine|bureau|couloir", t)
        several = [z for z in _zones(t) if z[0] != "length"]
        if sum(n for *_, n in several) > 1:   # « 20 m² et 15 m² », « 3 murs de 4 x 2,7 », « salon 5x4 et chambre 4x3 hauteur 2,7 »
            h = parse_number(height.group(1)) if height and rooms else None
            terms = []
            for k, v, n in several:
                one = 2 * (v[0] + v[1]) * h if k == "pair" and h else v[0] * v[1] if k == "pair" else v
                what = f"2 × ({v[0]:g} + {v[1]:g}) × {h:g}" if k == "pair" and h else f"{v[0]:g} × {v[1]:g}" if k == "pair" else f"{v:g}"
                terms.append((n, one, what))
            area_m = round_qty(sum(n * one for n, one, _ in terms), 2)
            from_pair = False
            note = ("Surface = " + " + ".join(f"{n} × {what}" if n > 1 else what for n, _, what in terms) + f" = {area_m:g} m²"
                    + (" (murs des pièces ; portes et fenêtres non déduites)." if h else "."))
        if from_pair:
            a, b = pair
            if height and rooms:
                h = parse_number(height.group(1))
                area_m = round_qty(2 * (a + b) * h, 2)
                note = (f"Surface = murs de la pièce : 2 × ({a:g} + {b:g}) × {h:g} = {area_m:g} m². "
                        "Portes et fenêtres non déduites (surface un peu surestimée).")
            else:
                note = (f"Surface = {a:g} × {b:g} = {area_m:g} m² (une seule face). "
                        "Pour peindre les murs d'une pièce, donnez aussi la hauteur.")
        result = calculate_paint(area_m, coats=coats)
        if note:
            result.assumptions.insert(0, note)
        return result

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
        skim = re.search(r"lissage|ratissage|finition|skim", t) and not tm
        passes = re.search(r"(\d+|une|un|deux|trois|quatre)\s*(?:passes?|couches?)", t)
        n_pass = _count(passes.group(1)) if passes else 2
        if tm:
            th = parse_number(tm.group(1))
        elif skim:   # lissage : une pellicule par passe, pas 10 mm d'enduit (avant : 330 kg pour 30 m²)
            th = float(n_pass)
        result = calculate_plaster(area_m, th, waste=max(waste, 0.10))
        if skim:
            result.assumptions.insert(0, f"Lissage : ≈ 1 mm par passe, {n_pass} passe(s)" + ("" if passes else " (non précisé)")
                                         + " — ordre de grandeur, à confirmer avec la fiche du produit.")
        return result

    if kind == "a_preciser":
        what = f"{area_m:g} m²" if area_m is not None else (f"{pair[0]:g} × {pair[1]:g} m" if pair else "la surface")
        return CalcResult(
            kind="a_preciser", title="Plafond ou cloison ?",
            understanding=f"{what} : l'ouvrage n'est pas précisé (plafond et cloison n'ont pas la même ossature).",
            inputs={"area": area_m} if area_m is not None else {},
            missing=["Ouvrage : faux plafond BA13 (tiges, pivots, chevilles à laiton, fourrures, cornières, chevilles à frapper) "
                     "ou cloison sèche (rails, montants, chevilles à frapper, vis 9 mm) ?"],
            next_step="Dis-moi « plafond » ou « cloison » et je calcule tout le matériel.")
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


# ---------- vérificateur indépendant ----------
# Recalcule les résultats clés AUTREMENT (fractions exactes, autre formulation) et compare. Un écart = un bug du moteur :
# il est signalé, jamais caché. Aucune IA ici.

def _F(x: Any) -> Fraction:
    return Fraction(str(x))


def _min_count(need: Fraction, unit: Fraction) -> int:
    """Plus petit entier n tel que n × unit ≥ need (0 si rien à couvrir)."""
    if need <= 0:
        return 0
    n = need // unit
    return int(n if n * unit >= need else n + 1)


def verify(result: "CalcResult") -> dict[str, Any]:
    problems: list[str] = []
    for q in result.quantities:
        v = q.quantity
        if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v < 0:
            problems.append(f"{q.name} : quantité invalide ({v}).")
        if not q.unit:
            problems.append(f"{q.name} : unité manquante.")
    inp, qty = result.inputs, {q.sku: q.quantity for q in result.quantities}
    step = {st.label.split(" (")[0]: st.result for st in result.steps}
    try:
        if result.kind == "partition" and inp:
            walls = [(_F(w), _F(h)) for w, h in inp.get("walls") or [(inp["length_m"], inp["height_m"])]]
            sides = int(inp["sides"])
            ops = sum((_F(o["width"]) * _F(o["height"]) * int(o["quantity"]) for o in inp.get("openings") or []), Fraction(0))
            gross = sum((L * H for L, H in walls), Fraction(0)) * sides
            net = max(gross - ops * sides, Fraction(0))
            if abs(_F(step.get("Surface brute", -1)) - gross) > Fraction(1, 1000):
                problems.append(f"Surface brute : moteur {step.get('Surface brute')} ≠ contrôle {float(gross):g} m².")
            if abs(_F(step.get("Surface nette", -1)) - net) > Fraction(1, 1000):
                problems.append(f"Surface nette : moteur {step.get('Surface nette')} ≠ contrôle {float(net):g} m².")
            sku, _ = board_sku(inp["board_width"], inp["board_height"])
            boards = _min_count(_F(round_qty(float(net), 3)) * (1 + _F(inp["waste"])), _F(inp["board_width"]) * _F(inp["board_height"]))
            if qty.get(sku) != boards:
                problems.append(f"Plaques : moteur {qty.get(sku)} ≠ contrôle {boards}.")
            bw, e = _F(inp["board_width"]), _F(inp["stud_spacing"])
            gaps = bw / e
            bar = _F(BAR_LENGTH_M)
            fx = {**FIXINGS_DEFAULT, **(inp.get("fixings") or {})}
            n = studs = pts = 0
            for L, H in walls:   # chaque cloison a ses montants, ses barres et ses chevilles
                n_w = (_min_count(L, bw) * int(gaps) + 1) if gaps >= 1 and gaps.denominator == 1 else _min_count(L, e) + 1
                full = int(H // bar)
                rest = H - full * bar
                studs += n_w if full == 0 else n_w * full if rest == 0 else n_w * full + _min_count(Fraction(n_w), Fraction(int(bar // rest)))
                pts += _min_count(2 * L, _F(fx["anchor_spacing_m"])) + 2
                n += n_w
            studs += DOOR_STUDS * sum(int(o["quantity"]) for o in inp.get("openings") or [] if o.get("kind") == "door")
            if qty.get("MONTANT-M48") != studs:
                problems.append(f"Montants : moteur {qty.get('MONTANT-M48')} ≠ contrôle {studs}.")
            bars = _min_count(2 * sum((L for L, _ in walls), Fraction(0)), _F(BAR_LENGTH_M))
            if qty.get("UC-RAILS-48-MM") != bars:
                problems.append(f"Rails : moteur {qty.get('UC-RAILS-48-MM')} ≠ contrôle {bars} barres.")
            packs = _min_count(Fraction(pts), Fraction(int(fx["anchors_per_pack"])))
            if "UC-PAQUET-CHEVILLES-A-FRAPPER" in qty and qty["UC-PAQUET-CHEVILLES-A-FRAPPER"] != packs:
                problems.append(f"Chevilles à frapper : moteur {qty['UC-PAQUET-CHEVILLES-A-FRAPPER']} ≠ contrôle {packs} paquet(s).")
            placed = n + DOOR_STUDS * sum(int(o["quantity"]) for o in inp.get("openings") or [] if o.get("kind") == "door")
            packs9 = _min_count(Fraction(placed * int(fx["screws9_per_stud"])), Fraction(int(fx["screws9_per_pack"])))
            if "UC-VIS-9-MM" in qty and qty["UC-VIS-9-MM"] != packs9:
                problems.append(f"Vis 9 mm : moteur {qty['UC-VIS-9-MM']} ≠ contrôle {packs9}.")
        elif result.kind == "partition_area" and inp:
            net = _F(inp["area_m2"]) * int(inp["sides"])
            sku, _ = board_sku(inp["board_width"], inp["board_height"])
            boards = _min_count(_F(round_qty(float(net), 3)) * (1 + _F(inp["waste"])), _F(inp["board_width"]) * _F(inp["board_height"]))
            if qty.get(sku) != boards:
                problems.append(f"Plaques : moteur {qty.get(sku)} ≠ contrôle {boards}.")
            if "MONTANT-M48" in qty or "UC-RAILS-48-MM" in qty:
                problems.append("Ossature présente alors que la longueur est inconnue : quantité inventée.")
        if inp and (result.kind == "moulure" or inp.get("moulure")):   # règles du patron : ⌈ ml / 3 ⌉ barres, ⌈ barres / 5 ⌉ colles
            mo = inp if result.kind == "moulure" else inp["moulure"]
            bars = _min_count(_F(mo["length_ml"]), _F(MOULURE_BAR_M))
            bar_sku = f"UC-MOULURE-TAILLE-{int(mo['taille'])}-BARRE-DE-3-M"
            glue_sku = "UC-COLLE-A-POMPE" if mo.get("colle") == "pompe" else "UC-COLLE-SILICONE"
            if qty.get(bar_sku) != bars:
                problems.append(f"Moulures : moteur {qty.get(bar_sku)} ≠ contrôle {bars} barres.")
            if qty.get(glue_sku) != _min_count(Fraction(bars), Fraction(MOULURE_BARS_PER_GLUE)):
                problems.append(f"Colles : moteur {qty.get(glue_sku)} ≠ contrôle {_min_count(Fraction(bars), Fraction(MOULURE_BARS_PER_GLUE))}.")
        if result.kind == "ceiling" and inp:
            zones = [(_F(a), _F(b)) for a, b in inp.get("zones") or [(inp["length_m"], inp["width_m"])]]
            area = sum((a * b for a, b in zones), Fraction(0))
            if abs(_F(step.get("Surface", -1)) - area) > Fraction(1, 1000):
                problems.append(f"Surface : moteur {step.get('Surface')} ≠ contrôle {float(area):g} m².")
            pers = [2 * (a + b) for a, b in zones]   # cornière de rive : chaque zone a ses 4 côtés
            rive = _min_count(sum(pers, Fraction(0)), _F(BAR_LENGTH_M))
            if "UC-CORNIERES" in qty and qty["UC-CORNIERES"] != rive:
                problems.append(f"Cornières : moteur {qty['UC-CORNIERES']} ≠ contrôle {rive} barres.")
            fx = {**FIXINGS_DEFAULT, **(inp.get("fixings") or {})}
            pts = sum(_min_count(per, _F(fx["anchor_spacing_m"])) + 4 for per in pers)
            packs = _min_count(Fraction(pts), Fraction(int(fx["anchors_per_pack"])))
            if "UC-PAQUET-CHEVILLES-A-FRAPPER" in qty and qty["UC-PAQUET-CHEVILLES-A-FRAPPER"] != packs:
                problems.append(f"Chevilles à frapper : moteur {qty['UC-PAQUET-CHEVILLES-A-FRAPPER']} ≠ contrôle {packs} paquet(s).")
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        problems.append(f"Contrôle impossible : {type(exc).__name__}.")
    return {"ok": not problems, "problems": problems,
            "note": "Contrôle indépendant (recalcul exact) : OK." if not problems else "ÉCART DÉTECTÉ : ne pas utiliser ce calcul sans vérification."}
