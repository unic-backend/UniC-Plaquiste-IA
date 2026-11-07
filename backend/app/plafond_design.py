"""Plafonds décoratifs proposés au client : des idées DESSINÉES (vue de dessus cotée) pour une pièce, avec les longueurs utiles.

Styles : caisson central (décaissé), gorge lumineuse périphérique (ruban LED caché), bandeau périphérique, îlot suspendu.
Les dessins sont générés en code (cotes exactes, calculées depuis les dimensions du patron, jamais inventées) puis rendus en PNG
partageable par diagrams.render. Longueurs de retombée et de ruban LED, surface des retombées : de la géométrie. Les plaques des
retombées suivent la règle des plaques du moteur (⌈ S × (1 + d) / Splaque ⌉). L'ossature des retombées reste à chiffrer : signalé.
"""
from __future__ import annotations

import math
import re

from app import calc

STYLES = {
    "caisson": ("Caisson central", "Un décaissé au centre de la pièce, encadré d'une retombée : il donne du volume et souligne le centre."),
    "gorge": ("Gorge lumineuse", "Un bandeau tout autour avec un ruban LED caché : lumière douce et indirecte sur le plafond."),
    "bandeau": ("Bandeau périphérique", "Un bandeau abaissé le long des murs pour encastrer des spots ; le centre reste plat et haut."),
    "ilot": ("Îlot suspendu", "Un îlot rectangulaire au-dessus de la zone principale (salon, table), éclairé par LED sur son pourtour."),
}
DEFAULT_STYLES = ("caisson", "gorge", "ilot")
# styles conseillés selon la pièce, le plus adapté d'abord, et pourquoi (ce que le patron dirait au client)
ROOM_STYLES = [
    (r"salle (?:de|d')\s?(?:bain|eau)|douche|\bwc\b|toilettes?", ("bandeau",),
     "pièce humide : bandeau avec spots étanches, plaques hydrofuges"),
    (r"salle [àa] manger", ("ilot", "caisson", "gorge"), "l'îlot au-dessus de la table souligne le repas"),
    (r"salon|s[ée]jour|living|pi[eè]ce [àa] vivre", ("caisson", "ilot", "gorge"),
     "pièce à vivre : du volume au centre et une lumière d'ambiance"),
    (r"chambre", ("gorge", "caisson", "bandeau"), "chambre : lumière douce et indirecte pour le repos"),
    (r"cuisine", ("bandeau", "ilot"), "cuisine : spots au-dessus du plan de travail, îlot au-dessus de la table"),
    (r"couloir|\bhall\b|entr[ée]e|d[ée]gagement", ("bandeau", "gorge"), "pièce de passage : spots en ligne ou lumière rasante"),
    (r"bureau|boutique|magasin|commerce|accueil|r[ée]ception|showroom", ("bandeau", "ilot", "gorge"),
     "lieu de travail ou de vente : éclairage franc et un point fort pour l'œil"),
]
LONG_ROOM = 2.5   # longueur ≥ 2,5 × largeur : un caisson central paraîtrait étiré
GREEN, COPPER, LIGHT, INK = "#1f5e3b", "#b87333", "#e8f1ea", "#1d2321"


class DesignError(ValueError):
    pass


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


BA13_CM = 1.25  # épaisseur d'une BA13 (12,5 mm) : les faces courtes de la retombée se glissent entre les faces longues


def _pack(faces: list[tuple[str, float]], stock_cm: float) -> tuple[list[dict], list[list]]:
    """Chaque face coupée en longueurs de stock (barre, bande) puis morceaux rangés du plus long au plus court dans le stock déjà
    entamé avant d'en couper un neuf : les chutes servent. Rend le détail par face et le contenu de chaque stock [reste, morceaux]."""
    detail, pieces = [], []
    for face, length in faces:
        rest = round(length % stock_cm, 1)
        cut = [float(stock_cm)] * int(length // stock_cm) + ([rest] if rest > 0 else [])
        detail.append({"face": face, "longueur_cm": length, "morceaux_cm": cut})
        pieces += [(c, face) for c in cut]
    bins: list[list] = []
    for length, face in sorted(pieces, key=lambda x: -x[0]):
        box = next((b for b in bins if b[0] + 1e-9 >= length), None)
        if box is None:
            box = [float(stock_cm), []]
            bins.append(box)
        box[0] = round(box[0] - length, 1)
        box[1].append((length, face))
    return detail, bins


def _bars(iw: float, ih: float) -> dict:
    """Ossature des retombées, méthode du patron : en haut une fourrure sur tout le tour (elle sert aussi de rive au niveau haut),
    en bas une cornière sur tout le tour. Mêmes coupes pour les deux, dans des barres de 2,80 m."""
    bar = round(calc.BAR_LENGTH_M * 100)
    detail, bins = _pack([("A", round(iw * 100, 1)), ("B", round(ih * 100, 1)), ("C", round(iw * 100, 1)), ("D", round(ih * 100, 1))], bar)
    return {"barre_cm": bar, "faces": detail, "barres": len(bins), "chute_cm": round(sum(b[0] for b in bins), 1)}


def _strips(iw: float, ih: float, retombee_m: float, board_width: float, board_height: float) -> dict:
    """Découpe des retombées : bandes de la hauteur de la retombée, coupées dans la longueur de la plaque (1,20 × 2 m → bandes de 2 m).
    Faces longues A et C à la cote du rectangle, faces courtes B et D moins deux épaisseurs de plaque (elles se glissent entre A et C).
    Morceaux rangés du plus long au plus court dans les bandes déjà entamées avant d'en couper une neuve (les chutes servent)."""
    h, bw, bl = round(retombee_m * 100, 1), round(board_width * 100), round(board_height * 100)
    per_board = int(bw // h) if h > 0 else 0
    if per_board < 1:
        raise DesignError(f"Retombée de {_fmt(h)} cm plus haute que la plaque ({bw} cm) : impossible en une bande.")
    faces = [("A", round(iw * 100, 1)), ("B", round(ih * 100 - 2 * BA13_CM, 1)), ("C", round(iw * 100, 1)), ("D", round(ih * 100 - 2 * BA13_CM, 1))]
    detail, bands = _pack(faces, bl)
    return {"bande_cm": h, "longueur_bande_cm": bl, "bandes_par_plaque": per_board, "faces": detail, "bandes": len(bands),
            "plaques": math.ceil(len(bands) / per_board), "chute_cm": round(sum(b[0] for b in bands), 1),
            "plan_bandes": [[{"face": f, "cm": c} for c, f in b[1]] for b in bands]}


def design(style: str, length_m: float, width_m: float, *, marge_m: float = 0.6, retombee_m: float = 0.15,
           board_width: float = 1.2, board_height: float = 2.0) -> dict:
    """Géométrie d'un style pour une pièce L × l (m) : rectangle intérieur, retombée, ruban LED, plaques des retombées
    (comptées sur la découpe réelle des bandes, comme le plan de pose : aucune plaque ne se vend en morceaux)."""
    if style not in STYLES:
        raise DesignError(f"Style inconnu : {style}. Choix : {', '.join(STYLES)}.")
    L, W = max(length_m, width_m), min(length_m, width_m)
    calc.check_inputs(positive={"longueur": L, "largeur": W, "retombée": retombee_m, "marge": marge_m})
    if W < 1.6:
        raise DesignError("Pièce trop étroite (moins de 1,60 m) pour un plafond décoratif : propose un plafond plat.")
    marge = min(marge_m, round((W - 1.0) / 2, 2))
    if style == "ilot":
        iw, ih = round(L / 2, 2), round(W / 2, 2)
    else:
        iw, ih = round(L - 2 * marge, 2), round(W - 2 * marge, 2)
    per = round(2 * (iw + ih), 2)
    area = round(per * retombee_m, 2)
    led = per if style in ("caisson", "gorge", "ilot") else 0.0
    name, idea = STYLES[style]
    return {"style": style, "nom": name, "idee": idea, "piece": [L, W], "marge_m": marge if style != "ilot" else None,
            "interieur": [iw, ih], "retombee_m": retombee_m, "retombee_ml": per, "retombee_m2": area, "led_ml": led,
            "plaques_retombees": _strips(iw, ih, retombee_m, board_width, board_height)["plaques"], "ossature": _bars(iw, ih),
            "svg": _svg(style, name, L, W, marge, iw, ih, retombee_m, led)}


def _svg(style: str, name: str, L: float, W: float, marge: float, iw: float, ih: float, retombee: float, led: float) -> str:
    """Vue de dessus cotée, 800 × 600 : murs en vert, partie décorative en vert clair, ruban LED en cuivre pointillé."""
    scale = min(620 / L, 380 / W)
    rw, rh = L * scale, W * scale
    x0, y0 = (800 - rw) / 2, 90 + (400 - rh) / 2
    ix, iy, iww, ihh = x0 + (rw - iw * scale) / 2, y0 + (rh - ih * scale) / 2, iw * scale, ih * scale
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" font-family="Arial">',
             '<rect x="0" y="0" width="800" height="600" fill="#ffffff"/>',
             f'<text x="400" y="42" font-size="26" font-weight="bold" fill="{GREEN}" text-anchor="middle">{name} — {_fmt(L)} × {_fmt(W)} m</text>',
             f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rw:.1f}" height="{rh:.1f}" fill="#ffffff" stroke="{INK}" stroke-width="6"/>']
    if style in ("gorge", "bandeau"):   # bandeau tout autour : la couronne entre les murs et le rectangle intérieur
        parts.append(f'<path d="M{x0:.1f},{y0:.1f} h{rw:.1f} v{rh:.1f} h-{rw:.1f} Z M{ix:.1f},{iy:.1f} v{ihh:.1f} h{iww:.1f} v-{ihh:.1f} Z" '
                     f'fill="{LIGHT}" fill-rule="evenodd" stroke="{GREEN}" stroke-width="3"/>')
    else:   # caisson ou îlot : le rectangle intérieur porte le décor
        parts.append(f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iww:.1f}" height="{ihh:.1f}" fill="{LIGHT}" stroke="{GREEN}" stroke-width="3"/>')
    if led:
        d = 7
        parts.append(f'<rect x="{ix - d:.1f}" y="{iy - d:.1f}" width="{iww + 2 * d:.1f}" height="{ihh + 2 * d:.1f}" fill="none" '
                     f'stroke="{COPPER}" stroke-width="3" stroke-dasharray="10 6"/>')
    if style == "bandeau":   # emplacement de spots, à titre d'exemple : un tous les ~1 m le long du bandeau
        mid = marge * scale / 2
        for side_len, horiz, base in ((rw, True, y0 + mid), (rw, True, y0 + rh - mid), (rh, False, x0 + mid), (rh, False, x0 + rw - mid)):
            n = max(2, round(side_len / scale))
            for k in range(1, n):
                cx, cy = (x0 + side_len * k / n, base) if horiz else (base, y0 + side_len * k / n)
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{COPPER}"/>')
    parts += [   # cotes
        f'<text x="{x0 + rw / 2:.1f}" y="{y0 - 14:.1f}" font-size="18" fill="{INK}" text-anchor="middle">{_fmt(L)} m</text>',
        f'<text x="{x0 - 14:.1f}" y="{y0 + rh / 2:.1f}" font-size="18" fill="{INK}" text-anchor="end">{_fmt(W)} m</text>',
        f'<text x="{ix + iww / 2:.1f}" y="{iy + ihh / 2 + 6:.1f}" font-size="17" fill="{GREEN}" text-anchor="middle">{_fmt(iw)} × {_fmt(ih)} m</text>',
        f'<text x="400" y="545" font-size="15" fill="{INK}" text-anchor="middle">Retombée {_fmt(retombee * 100)} cm sur {_fmt(2 * (iw + ih))} ml'
        + (f'  ·  ruban LED {_fmt(led)} ml (pointillé cuivre)' if led else '') + (f'  ·  marge {_fmt(marge)} m' if style != "ilot" else '')
        + ('  ·  points cuivre : spots (exemple)' if style == "bandeau" else '') + '</text>',
        '<text x="400" y="575" font-size="14" fill="#5b625f" text-anchor="middle">Vue de dessus — proposition UniC Plaquiste, cotes en mètres</text>',
        '</svg>']
    return "".join(parts)


def suggest(piece: str, length_m: float, width_m: float) -> tuple[tuple, str]:
    """Styles à proposer quand le patron n'en choisit pas : selon la pièce nommée, sinon selon la forme de la pièce."""
    low = (piece or "").lower()
    for words, styles, why in ROOM_STYLES:
        if re.search(words, low):
            return styles, why
    L, W = max(length_m, width_m), min(length_m, width_m)
    if W > 0 and L / W >= LONG_ROOM:
        return ("bandeau", "gorge", "caisson"), "pièce longue : le bandeau et la gorge suivent les murs, un caisson central paraîtrait étiré"
    return DEFAULT_STYLES, ""


def designs(length_m: float, width_m: float, styles: list | None = None, piece: str = "", **kw) -> list[dict]:
    chosen = [s for s in (styles or suggest(piece, length_m, width_m)[0]) if s in STYLES][:4] or list(DEFAULT_STYLES)
    return [design(s, length_m, width_m, **kw) for s in chosen]


def trace_decoupe(style: str, length_m: float, width_m: float, *, marge_m: float = 0.6, retombee_m: float = 0.15,
                  board_width: float = 1.2, board_height: float = 2.0) -> dict:
    """Plan de TRAÇAGE et de DÉCOUPE d'un décor, pour les ouvriers : où tracer au cordeau (distances aux murs, contrôle d'équerre par
    les diagonales), puis comment couper les bandes de retombée dans les plaques (cotes de chaque face, morceaux, chutes). Géométrie
    exacte depuis les dimensions du patron ; ossature des retombées selon sa méthode (fourrure en haut, cornière en bas)."""
    d = design(style, length_m, width_m, marge_m=marge_m, retombee_m=retombee_m, board_width=board_width, board_height=board_height)
    L, W = d["piece"]
    iw, ih = d["interieur"]
    ax, ay = (round((L - iw) / 2, 2), round((W - ih) / 2, 2)) if style == "ilot" else (d["marge_m"], d["marge_m"])
    diag = round(math.hypot(iw, ih), 2)
    cut = _strips(iw, ih, retombee_m, board_width, board_height)
    where = "le décaissé central" if style == "caisson" else "l'îlot" if style == "ilot" else "le bord intérieur du bandeau"
    tracage = [
        (f"Trouve le milieu de chaque mur et trace les deux axes de la pièce : {where} est centré dessus." if style == "ilot" else
         f"Mesure {_fmt(ax)} m depuis chaque mur, aux deux bouts du mur, et claque le cordeau : 4 lignes."),
        f"Rectangle tracé : {_fmt(iw)} × {_fmt(ih)} m ({where}), à {_fmt(ay)} m des murs longs et {_fmt(ax)} m des murs courts.",
        f"Équerre : les deux diagonales doivent mesurer {_fmt(diag)} m chacune. Si elles diffèrent, décale un coin jusqu'à l'égalité.",
        f"Hauteur : la retombée descend de {_fmt(retombee_m * 100)} cm sous le plafond ; reporte ce niveau au laser sur le pourtour.",
    ]
    faces_txt = "; ".join(f"face {f['face']} {_fmt(f['longueur_cm'])} cm = " + " + ".join(_fmt(m) for m in f["morceaux_cm"])
                          for f in cut["faces"])
    decoupe = [
        f"Bandes de {_fmt(cut['bande_cm'])} cm coupées dans la longueur des plaques : {cut['bandes_par_plaque']} bandes de "
        f"{_fmt(cut['longueur_bande_cm'])} cm par plaque (trace au cutter, casse franche, ponce le chant).",
        f"Faces longues A et C à la cote du rectangle ; faces courtes B et D moins {_fmt(2 * BA13_CM)} cm (elles se glissent entre A et C).",
        f"Morceaux : {faces_txt}.",
        f"Total : {cut['bandes']} bande{'s' if cut['bandes'] > 1 else ''}, soit {cut['plaques']} plaque{'s' if cut['plaques'] > 1 else ''} ; "
        f"chute {_fmt(cut['chute_cm'])} cm de bande.",
        "Jonction de deux morceaux : toujours sur l'ossature, jamais dans le vide ; décale les jonctions d'une face à l'autre.",
    ]
    os_ = d["ossature"]
    bars_txt = "; ".join(f"{f['face']} {_fmt(f['longueur_cm'])} = " + " + ".join(_fmt(m) for m in f["morceaux_cm"]) for f in os_["faces"])
    ossature = [
        "En haut : en posant les fourrures, prévois une fourrure sur la ligne tracée, tout le tour ; la retombée se visse dessus "
        "(elle fait fourrure et rive du niveau haut).",
        "En bas : une cornière sur tout le tour couvre et tient le bas de la retombée.",
        f"Coupes (cm), les mêmes pour la fourrure et la cornière : {bars_txt}.",
        f"Total : {os_['barres']} barre{'s' if os_['barres'] > 1 else ''} de fourrure + {os_['barres']} barre{'s' if os_['barres'] > 1 else ''} "
        f"de cornière ({calc.BAR_TXT} m).",
    ]
    return {"style": style, "nom": d["nom"], "piece": [L, W], "interieur": [iw, ih], "distances_murs_m": [ax, ay], "diagonale_m": diag,
            "tracage": tracage, "decoupe": decoupe, "ossature": ossature, "barres_ossature": d["ossature"]["barres"], "bandes": cut, "plaques_retombees": cut["plaques"],
            "svg": _svg_trace(style, d["nom"], L, W, iw, ih, ax, ay, diag, cut, d["ossature"]["barres"])}


def _svg_trace(style: str, name: str, L: float, W: float, iw: float, ih: float, ax: float, ay: float, diag: float, cut: dict,
               bars: int) -> str:
    """800 × 900 : en haut la pièce vue de dessus (rectangle à tracer, diagonales, faces A-D, partie décorée en vert clair) ; en bas
    les bandes à couper, les identiques regroupées (« × 12 »), chaque morceau marqué de sa face et de sa longueur."""
    scale = min(560 / L, 280 / W)
    rw, rh = L * scale, W * scale
    x0, y0 = (800 - rw) / 2, 80
    ix, iy, iww, ihh = x0 + ax * scale, y0 + ay * scale, iw * scale, ih * scale
    halo = 'paint-order="stroke" stroke="#ffffff" stroke-width="4"'
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 900" font-family="Arial">',
         '<rect x="0" y="0" width="800" height="900" fill="#ffffff"/>',
         f'<text x="400" y="40" font-size="24" font-weight="bold" fill="{GREEN}" text-anchor="middle">Traçage et découpe — {name}</text>',
         f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rw:.1f}" height="{rh:.1f}" fill="#ffffff" stroke="{INK}" stroke-width="5"/>']
    if style in ("gorge", "bandeau"):   # la couronne le long des murs porte le décor
        p.append(f'<path d="M{x0:.1f},{y0:.1f} h{rw:.1f} v{rh:.1f} h-{rw:.1f} Z M{ix:.1f},{iy:.1f} v{ihh:.1f} h{iww:.1f} v-{ihh:.1f} Z" '
                 f'fill="{LIGHT}" fill-rule="evenodd"/>')
    else:
        p.append(f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iww:.1f}" height="{ihh:.1f}" fill="{LIGHT}"/>')
    p += [f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iww:.1f}" height="{ihh:.1f}" fill="none" stroke="{GREEN}" stroke-width="3" stroke-dasharray="12 6"/>',
          f'<path d="M{ix:.1f},{iy:.1f} L{ix + iww:.1f},{iy + ihh:.1f} M{ix + iww:.1f},{iy:.1f} L{ix:.1f},{iy + ihh:.1f}" stroke="{COPPER}" stroke-width="1.5" stroke-dasharray="4 5"/>',
          f'<text x="{ix + iww / 2:.1f}" y="{iy + ihh / 2 + 6:.1f}" font-size="17" font-weight="bold" fill="{GREEN}" text-anchor="middle" {halo}>{_fmt(iw)} × {_fmt(ih)} m</text>',
          f'<text x="{x0 + rw / 2:.1f}" y="{y0 - 10:.1f}" font-size="15" fill="{INK}" text-anchor="middle">{_fmt(L)} m</text>',
          f'<text x="{x0 - 10:.1f}" y="{y0 + rh / 2:.1f}" font-size="15" fill="{INK}" text-anchor="end">{_fmt(W)} m</text>']
    for face, tx, ty in (("A", ix + iww / 2, iy + 18), ("B", ix + iww - 14, iy + ihh / 2 + 5), ("C", ix + iww / 2, iy + ihh - 8), ("D", ix + 14, iy + ihh / 2 + 5)):
        p.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="15" font-weight="bold" fill="{GREEN}" text-anchor="middle" {halo}>{face}</text>')
    p.append(f'<text x="400" y="{y0 + rh + 30:.1f}" font-size="15" fill="{INK}" text-anchor="middle">Tracé (pointillé vert) à {_fmt(ay)} m des murs '
             f'longs et {_fmt(ax)} m des murs courts · diagonales (cuivre) {_fmt(diag)} m chacune</text>')
    groups: list[list] = []   # [nombre, bande]
    for band in cut["plan_bandes"]:
        same = next((g for g in groups if g[1] == band), None)
        if same:
            same[0] += 1
        else:
            groups.append([1, band])
    top = y0 + rh + 72
    p.append(f'<text x="40" y="{top:.1f}" font-size="17" font-weight="bold" fill="{INK}">Bandes de {_fmt(cut["bande_cm"])} × '
             f'{_fmt(cut["longueur_bande_cm"])} cm : {cut["bandes"]} bande{"s" if cut["bandes"] > 1 else ""}, '
             f'{cut["plaques"]} plaque{"s" if cut["plaques"] > 1 else ""} ({cut["bandes_par_plaque"]} bandes par plaque)</text>')
    shown = groups[:12]
    sx = 640 / cut["longueur_bande_cm"]
    bh = max(18.0, min(30.0, (830 - top - 30) / max(1, len(shown)) - 6))
    for k, (n, band) in enumerate(shown):
        y = top + 16 + k * (bh + 6)
        x = 40.0
        p.append(f'<text x="40" y="{y + bh / 2 + 5:.1f}" font-size="15" font-weight="bold" fill="{INK}">{n} ×</text>')
        x = 110.0
        p.append(f'<rect x="110" y="{y:.1f}" width="640" height="{bh:.1f}" fill="#f1f1ee" stroke="#9aa19d" stroke-width="1"/>')
        for piece in band:
            w = piece["cm"] * sx
            p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="{LIGHT}" stroke="{GREEN}" stroke-width="1.5"/>')
            if w > 44:
                p.append(f'<text x="{x + w / 2:.1f}" y="{y + bh / 2 + 5:.1f}" font-size="13" fill="{INK}" text-anchor="middle">'
                         f'{piece["face"]} · {_fmt(piece["cm"])}</text>')
            x += w
    if len(groups) > len(shown):
        p.append(f'<text x="40" y="{top + 16 + len(shown) * (bh + 6) + 14:.1f}" font-size="13" fill="{INK}">… et {len(groups) - len(shown)} '
                 'autre(s) découpe(s) : liste complète dans la réponse</text>')
    p.append(f'<text x="400" y="860" font-size="15" font-weight="bold" fill="{INK}" text-anchor="middle">Ossature : fourrure en haut + '
             f'cornière en bas, tout le tour — {bars} barre{"s" if bars > 1 else ""} de chaque</text>')
    p += ['<text x="400" y="885" font-size="13" fill="#5b625f" text-anchor="middle">Gris : chute. Cotes de découpe en cm. '
          'Faces B et D raccourcies de deux épaisseurs de plaque (2 × 12,5 mm).</text>', '</svg>']
    return "".join(p)
