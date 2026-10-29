"""Plan de pose d'un faux plafond (calepinage) DESSINÉ pour les ouvriers : où passent les fourrures, où vont les tiges, comment
poser les plaques. Règles du patron (Sénégal) :

- fourrures tous les 50 cm, la première et la dernière contre le mur ; barres de 2,80 m ;
- tiges : la première à 30 cm du mur, puis une tous les 90 cm, toujours une près de l'autre mur (calc.hanger_positions) ;
- plaque de 1,20 × 2 m (2,50 seulement si le patron le dit) posée EN TRAVERS des fourrures : 50 cm × 4 = 2 m, chaque bout tombe
  sur une fourrure (à 60 cm, ce serait la largeur de 1,20 m qui tomberait sur les fourrures) ;
- plaques entières posées d'un mur jusqu'à l'autre : seule la dernière de chaque rangée est coupée (6,47 m = 3 plaques de 2 m
  + un morceau de 47 cm).

Mêmes nombres que le devis (calc.ceiling_run / ceiling_layout). Plaques comptées comme le patron : entières dans chaque sens
(3 × 3 = 9), puis chaque taille de morceau convertie en plaques ENTIÈRES (aucune fourniture ne vend de morceaux : 47 × 120 cm,
une plaque de 2 m en donne 4) ; les morceaux en trop d'une plaque entamée servent aux plus petits. Total comparé au devis.
Dessin : fourrures verticales (bleu), tiges en points rouges, cornière de rive en orange, plaques en vert (coupées en vert pâle,
cote de coupe en cm).
"""
from __future__ import annotations

from app import calc

WALL, FURRING, HANGER, ANGLE, DIM = "#263238", "#1565c0", "#d32f2f", "#ef6c00", "#37474f"
BOARD_STROKE, BOARD_FULL, BOARD_CUT = "#2e7d32", "#c8e6c9", "#f1f8e9"
MAX_AREA_M2 = 300   # au-delà, le dessin devient illisible : un plan par pièce


class PlanError(ValueError):
    pass


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _len(v: float) -> str:
    """Longueur de plaque comme le patron la dit : « 2 m », « 2,50 m »."""
    return _fmt(v) if v == int(v) else f"{v:.2f}".replace(".", ",")


def _cuts(total: int, step: int) -> list[int]:
    """Bords des plaques le long d'un côté de `total` cm : plaques entières depuis le mur, la dernière coupée."""
    return list(range(0, total, step)) + [total]


def _decoupe(groups: list[tuple[int, int, int]], pw: int, ph: int) -> list[dict]:
    """Méthode du patron : aucune fourniture ne vend de morceaux, chaque morceau se compte en plaques ENTIÈRES.
    `groups` = (longueur dans le sens des 2 m, largeur dans le sens des 1,20 m, nombre) en cm. Pour chaque taille : combien de
    morceaux une plaque donne (47 × 120 dans une plaque de 2 m : 4), donc combien de plaques. Les morceaux d'une plaque déjà
    entamée qui restent (chutes de même taille) servent d'abord aux morceaux plus petits. Sens de la plaque gardé."""
    spares: list[list[int]] = []   # [longueur, largeur, nombre] : morceaux taillés en trop, réutilisables
    out = []
    for ln, wd, n in sorted(groups, key=lambda g: g[0] * g[1], reverse=True):
        need, from_spares = n, 0
        for sp in spares:
            per = (sp[0] // ln) * (sp[1] // wd)
            if need and sp[2] and per:
                use = min(sp[2], -(-need // per))
                got = min(need, use * per)
                sp[2] -= use
                need -= got
                from_spares += got
        per_board = (ph // ln) * (pw // wd)
        boards = -(-need // per_board) if need else 0
        if boards * per_board > need:
            spares.append([ln, wd, boards * per_board - need])
        out.append({"morceau": f"{ln} × {wd} cm", "nombre": n, "par_plaque": per_board, "plaques": boards,
                    "pris_dans_les_chutes": from_spares})
    return out


def _decoupe_txt(d: dict) -> str:
    txt = f"{d['nombre']} morceau{'x' if d['nombre'] > 1 else ''} de {d['morceau']}"
    if d["pris_dans_les_chutes"] == d["nombre"]:
        return f"{txt} : pris dans les chutes → 0 plaque"
    chutes = f" ({d['pris_dans_les_chutes']} pris dans les chutes)" if d["pris_dans_les_chutes"] else ""
    return f"{txt}{chutes} : une plaque en donne {d['par_plaque']} → {d['plaques']} plaque{'s' if d['plaques'] > 1 else ''}"


def plan(length_m: float, width_m: float, *, board_width: float = calc.DEFAULTS["board_width_m"],
         board_height: float = calc.DEFAULTS["board_height_m"], waste: float = calc.DEFAULTS["waste"],
         entraxe_cm: int = 50) -> dict:
    """Plan de pose d'un plafond rectangulaire L × l (m) : fourrures, tiges, plaques entières et coupées, et le dessin.
    `entraxe_cm` : 50 (défaut, plaque en travers des fourrures) ou 60 (tiges 60 × 60, plaque dans le sens des fourrures)."""
    calc.check_inputs(positive={"longueur": length_m, "largeur": width_m, "largeur de plaque": board_width,
                                "hauteur de plaque": board_height})
    if length_m * width_m > MAX_AREA_M2:
        raise PlanError(f"Plafond de plus de {MAX_AREA_M2} m² : fais un plan par pièce (plus lisible pour les ouvriers).")
    spacing, step = calc.grid(entraxe_cm)
    run, across = calc.ceiling_run(length_m, width_m, entraxe_cm)   # fourrures le long de `run`, espacées sur `across`
    rows, hangers, furring_ml = calc.ceiling_layout(run, across, entraxe_cm)
    run_cm, across_cm = round(run * 100), round(across * 100)
    sp_cm, h_cm = round(spacing * 100), round(step * 100)
    first_cm = round(calc.HANGER_FIRST_M * 100)
    pw, ph = round(min(board_width, board_height) * 100), round(max(board_width, board_height) * 100)
    lines = [k * sp_cm for k in range(rows - 1)] + [across_cm]   # fourrures : la première et la dernière contre le mur
    ties = [round(p * 100) for p in calc.hanger_positions(run, step)]

    # trame 50 : plaque EN TRAVERS (2 m sur `across`, 50 × 4 = 2 m) ; trame 60 : plaque DANS LE SENS des fourrures (1,20 m sur
    # `across`, 60 × 2 = 1,20 m). Les plaques partent d'un mur, seule la dernière de chaque rangée est coupée.
    parallel = sp_cm != 50 and pw % sp_cm == 0
    l2, l12 = (run_cm, across_cm) if parallel else (across_cm, run_cm)   # côté qui reçoit les 2 m, côté qui reçoit les 1,20 m
    s_run, s_across = (ph, pw) if parallel else (pw, ph)
    along, cross = _cuts(run_cm, s_run), _cuts(across_cm, s_across)
    tiles = []
    for a, a1 in zip(along, along[1:]):
        for b, b1 in zip(cross, cross[1:]):
            ln, wd = (a1 - a, b1 - b) if parallel else (b1 - b, a1 - a)   # morceau : longueur (sens des 2 m) × largeur
            tiles.append((a, b, a1 - a, b1 - b, ln == ph and wd == pw, f"{ln}×{wd}"))
    # plaques entières : combien dans chaque sens (comme le patron compte), puis les morceaux convertis en plaques entières
    n2, r2 = divmod(l2, ph)     # sens des 2 m : plaques entières + morceau au dernier mur
    n12, r12 = divmod(l12, pw)  # sens des 1,20 m : rangées entières + rangée coupée au dernier mur
    full = n2 * n12
    groups = [g for g in ((r2, pw, n12), (ph, r12, n2), (r2, r12, 1)) if g[0] and g[1] and g[2]]
    decoupe = _decoupe(groups, pw, ph)
    pieces = sum(d["nombre"] for d in decoupe)
    for_pieces = sum(d["plaques"] for d in decoupe)
    used = full + for_pieces
    quote = calc.boards_needed(round(length_m * width_m, 3), waste, board_width * board_height)
    bar = calc.BAR_TXT
    furring_bars = calc.ceil_int(furring_ml / calc.BAR_LENGTH_M)
    perimeter = round(2 * (run + across), 2)
    angle_bars = calc.ceil_int(perimeter / calc.BAR_LENGTH_M)
    if parallel:
        pose = (f"Plaques de {_len(ph / 100)} m dans le sens des fourrures ({sp_cm} cm × {pw // sp_cm} = {_len(pw / 100)} m : "
                f"chaque bord tombe sur une fourrure)")
    else:
        pose = (f"Plaques de {_len(ph / 100)} m en travers des fourrures "
                + (f"({sp_cm} cm × {ph // sp_cm} = {_len(ph / 100)} m : chaque bout tombe sur une fourrure)" if ph % sp_cm == 0
                   else "(bouts à reprendre sur une fourrure ajoutée)"))
    out = {
        "piece": [run, across], "entraxe_cm": sp_cm, "fourrures": rows, "fourrures_sens": f"dans le sens des {_fmt(run)} m", "fourrure_ml": furring_ml,
        "barres_fourrure": furring_bars, "tiges": hangers, "tiges_par_fourrure": len(ties), "cornieres": angle_bars,
        "plaque": f"{_len(pw / 100)} × {_len(ph / 100)} m", "plaques_entieres": full, "morceaux_coupes": pieces,
        "decoupe": decoupe, "plaques_pour_morceaux": for_pieces, "plaques_utilisees": used, "plaques_devis": quote,
        "consignes": [
            f"Fourrures dans le sens des {_fmt(run)} m : une tous les {sp_cm} cm, la première et la dernière contre le mur. "
            f"{rows} fourrures = {_fmt(furring_ml)} ml = {furring_bars} barres de {bar} m.",
            f"Tiges : la première à {first_cm} cm du mur, puis une tous les {h_cm} cm, la dernière près de l'autre mur. "
            f"{len(ties)} par fourrure = {hangers} tiges.",
            f"{pose}. Plaques entières d'un mur à l'autre : seule la dernière de chaque rangée est coupée.",
            f"Plaques entières : sens des {_fmt(l2 / 100)} m → {n2} plaque{'s' if n2 > 1 else ''} de "
            f"{_len(ph / 100)} m" + (f" + un morceau de {r2} cm" if r2 else "") + f" ; sens des {_fmt(l12 / 100)} m → "
            f"{n12} rangée{'s' if n12 > 1 else ''} de {_len(pw / 100)} m" + (f" + une rangée de {r12} cm" if r12 else "")
            + f" ; {n2} × {n12} = {full} plaque{'s' if full > 1 else ''} entière{'s' if full > 1 else ''}.",
            "Morceaux (comptés en plaques entières) : " + (" ; ".join(_decoupe_txt(d) for d in decoupe) if decoupe else "aucun") + ".",
            f"Total à acheter : {full} entières + {for_pieces} pour les morceaux = {used} plaques (devis : {quote}).",
            f"Cornières : périmètre {_fmt(perimeter)} ml = {angle_bars} barres de {bar} m.",
        ],
    }
    if used > quote:
        out["alerte"] = f"Ce plan consomme {used} plaques, le devis en prévoit {quote} : ajoute {used - quote} plaque(s)."
    out["svg"] = _svg(run_cm, across_cm, lines, ties, tiles, (sp_cm, first_cm, h_cm), [
        f"Plan de pose — plafond {_fmt(length_m)} × {_fmt(width_m)} m",
        f"Fourrures tous les {sp_cm} cm · tiges : {first_cm} cm du mur puis tous les {h_cm} cm · plaques "
        + ("dans le sens des fourrures" if parallel else "en travers"),
        f"{rows} fourrures ({furring_bars} barres de {bar} m) · {hangers} tiges · {angle_bars} cornières de {bar} m",
        f"{full} plaques entières + {for_pieces} pour les morceaux = {used} plaques à acheter (devis : {quote})",
        "Morceaux : " + (" · ".join(f"{d['nombre']} de {d['morceau'].replace(' × ', '×')} → " + (f"{d['plaques']} plaque{'s' if d['plaques'] > 1 else ''} "
                                                                           f"({d['par_plaque']} par plaque)" if d["plaques"] else "chutes")
                                    for d in decoupe) if decoupe else "aucun")])
    return out


def _svg(run_cm: int, across_cm: int, lines: list[int], ties: list[int], tiles: list, gaps: tuple[int, int, int],
         texts: list[str]) -> str:
    """Vue de dessus, fourrures VERTICALES : x = en travers des fourrures, y = le long des fourrures ; hauteur du dessin selon la
    pièce (lisible sur téléphone). Une couleur par matériau ; cotes 50 cm (fourrures), 30 cm puis 90 cm (tiges)."""
    sp_cm, first_cm, h_cm = gaps
    scale = min(700 / across_cm, 820 / run_cm)
    rw, rh = across_cm * scale, run_cm * scale
    x0, y0 = (900 - rw) / 2, 120
    H = round(y0 + rh + 205)
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {H}" font-family="Arial">',
         f'<rect x="0" y="0" width="900" height="{H}" fill="#ffffff"/>',
         f'<text x="450" y="42" font-size="28" font-weight="bold" fill="{BOARD_STROKE}" text-anchor="middle">{texts[0]}</text>',
         f'<text x="450" y="74" font-size="17" fill="{DIM}" text-anchor="middle">{texts[1]}</text>']
    labels = []
    for a, b, w, h, whole, name in tiles:   # w : le long des fourrures (vertical) ; h : en travers (horizontal)
        x, y = x0 + b * scale, y0 + a * scale
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{h * scale:.1f}" height="{w * scale:.1f}" '
                 f'fill="{BOARD_FULL if whole else BOARD_CUT}" stroke="{BOARD_STROKE}" stroke-width="1.5"/>')
        if not whole and w * scale >= 16:   # cote de coupe en cm : longueur × largeur du morceau
            txt = name if h * scale >= 58 else (str(h) if h * scale >= 26 else "")
            if txt:   # fond blanc : la cote reste lisible sur les fourrures et les tiges
                cx, cy, tw = x + h * scale / 2, y + w * scale / 2, len(txt) * 8.6 + 8
                labels += [f'<rect x="{cx - tw / 2:.1f}" y="{cy - 11:.1f}" width="{tw:.1f}" height="21" rx="4" fill="#ffffff" '
                           f'stroke="{BOARD_STROKE}" stroke-width="1"/>',
                           f'<text x="{cx:.1f}" y="{cy + 5:.1f}" font-size="14" font-weight="bold" fill="{BOARD_STROKE}" '
                           f'text-anchor="middle">{txt}</text>']
    p += [f'<line x1="{x0 + x * scale:.1f}" y1="{y0:.1f}" x2="{x0 + x * scale:.1f}" y2="{y0 + rh:.1f}" stroke="{FURRING}" '
          f'stroke-width="3"/>' for x in lines]
    p += [f'<circle cx="{x0 + x * scale:.1f}" cy="{y0 + y * scale:.1f}" r="5" fill="{HANGER}"/>' for x in lines for y in ties]
    p += labels + [
        f'<rect x="{x0 + 3:.1f}" y="{y0 + 3:.1f}" width="{rw - 6:.1f}" height="{rh - 6:.1f}" fill="none" stroke="{ANGLE}" stroke-width="4"/>',
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rw:.1f}" height="{rh:.1f}" fill="none" stroke="{WALL}" stroke-width="5"/>',
        f'<text x="{x0 + rw / 2:.1f}" y="{y0 - 14:.1f}" font-size="20" font-weight="bold" fill="{WALL}" text-anchor="middle">'
        f'{_fmt(across_cm / 100)} m</text>',
        f'<text x="{x0 - 14:.1f}" y="{y0 + rh / 2:.1f}" font-size="20" font-weight="bold" fill="{WALL}" text-anchor="end">'
        f'{_fmt(run_cm / 100)} m</text>']
    # cotes : 50 cm entre deux fourrures (sous le plafond) ; 30 cm puis 90 cm pour les tiges (à droite)
    yb, xr = y0 + rh + 18, x0 + rw + 16
    xa = x0 + min(sp_cm, across_cm) * scale
    p += [f'<path d="M{x0:.1f},{yb:.1f} H{xa:.1f} M{x0:.1f},{yb - 6:.1f} v12 M{xa:.1f},{yb - 6:.1f} v12" stroke="{DIM}" stroke-width="2"/>',
          f'<text x="{(x0 + xa) / 2:.1f}" y="{yb + 22:.1f}" font-size="15" font-weight="bold" fill="{FURRING}" '
          f'text-anchor="middle">{sp_cm} cm</text>']
    marks = [0] + ties[:2]
    for (t0, t1), label in zip(zip(marks, marks[1:]), (f"{first_cm} cm", f"{h_cm} cm")):
        ya, yz = y0 + t0 * scale, y0 + t1 * scale
        p += [f'<path d="M{xr:.1f},{ya:.1f} V{yz:.1f} M{xr - 6:.1f},{ya:.1f} h12 M{xr - 6:.1f},{yz:.1f} h12" stroke="{DIM}" stroke-width="2"/>',
              f'<text x="{xr + 10:.1f}" y="{(ya + yz) / 2 + 5:.1f}" font-size="15" font-weight="bold" fill="{HANGER}">{label}</text>']
    ty = y0 + rh + 78
    p += [f'<text x="450" y="{ty:.0f}" font-size="18" fill="{WALL}" text-anchor="middle">{texts[2]}</text>',
          f'<text x="450" y="{ty + 30:.0f}" font-size="19" font-weight="bold" fill="{WALL}" text-anchor="middle">{texts[3]}</text>',
          f'<text x="450" y="{ty + 56:.0f}" font-size="{15 if len(texts[4]) <= 105 else 13}" fill="{BOARD_STROKE}" '
          f'text-anchor="middle">{texts[4]}</text>']
    ly = ty + 96   # légende : une couleur par matériau
    p += [f'<circle cx="70" cy="{ly - 5:.0f}" r="6" fill="{HANGER}"/>',
          f'<text x="84" y="{ly:.0f}" font-size="15" fill="{WALL}">tige</text>',
          f'<line x1="140" y1="{ly - 5:.0f}" x2="175" y2="{ly - 5:.0f}" stroke="{FURRING}" stroke-width="4"/>',
          f'<text x="183" y="{ly:.0f}" font-size="15" fill="{WALL}">fourrure</text>',
          f'<line x1="265" y1="{ly - 5:.0f}" x2="300" y2="{ly - 5:.0f}" stroke="{ANGLE}" stroke-width="4"/>',
          f'<text x="308" y="{ly:.0f}" font-size="15" fill="{WALL}">cornière</text>',
          f'<rect x="390" y="{ly - 16:.0f}" width="30" height="20" fill="{BOARD_FULL}" stroke="{BOARD_STROKE}"/>',
          f'<text x="428" y="{ly:.0f}" font-size="15" fill="{WALL}">plaque entière</text>',
          f'<rect x="560" y="{ly - 16:.0f}" width="30" height="20" fill="{BOARD_CUT}" stroke="{BOARD_STROKE}"/>',
          f'<text x="598" y="{ly:.0f}" font-size="15" fill="{WALL}">plaque coupée (cm)</text>',
          '</svg>']
    return "".join(p)
