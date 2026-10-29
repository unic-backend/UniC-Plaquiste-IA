"""Plan de pose d'un faux plafond (calepinage) DESSINÉ pour les ouvriers : où passent les fourrures, où vont les tiges, comment
poser les plaques.

Mêmes règles que le moteur de calcul (calc.ceiling_run / ceiling_layout) : fourrures dans le sens qui demande le moins de tiges,
tous les 50 cm (la dernière contre le mur), tiges tous les 90 cm depuis le mur (la dernière contre l'autre mur), barres de
2,80 m (règle du patron au Sénégal) ; les nombres du plan sont ceux du devis.
Plaques posées en travers des fourrures, bouts sur une fourrure (la longueur de plaque est un multiple de 0,50 m), joints décalés
d'une demi-plaque d'une rangée à l'autre. Les morceaux coupés sont pris dans le moins de plaques possible (les chutes servent),
en gardant le sens de la plaque : le plan dit combien de plaques il consomme, à comparer au nombre du devis.
"""
from __future__ import annotations

from app import calc

GREEN, COPPER, LIGHT, CUT, INK, GREY = "#1f5e3b", "#b87333", "#e8f1ea", "#f6e6d6", "#1d2321", "#5b625f"
MAX_AREA_M2 = 300   # au-delà, le dessin devient illisible : un plan par pièce
MIN_PIECE_CM = 30   # en dessous, un morceau de plaque casse à la pose : le plan recentre les coupes pour l'éviter


class PlanError(ValueError):
    pass


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _len(v: float) -> str:
    """Longueur de plaque comme le patron la dit : « 2 m », « 2,50 m »."""
    return _fmt(v) if v == int(v) else f"{v:.2f}".replace(".", ",")


def _cuts(total: int, step: int, offset: int) -> list[int]:
    """Bords des plaques le long d'un côté de `total` cm : tous les `step` cm, décalés de `offset`."""
    edges = [0] + [x for x in range(offset or step, total, step)] + [total]
    return sorted(set(edges))


def _offset(total: int, size: int, grid: int, stagger: bool) -> int:
    """Premier bord (cm, sur la grille `grid`) qui évite les morceaux étroits aux murs, puis donne le moins de morceaux et le
    plus de plaques entières ; avec `stagger`, la rangée décalée d'une demi-plaque compte aussi."""
    def pieces(off: int) -> list[int]:
        edges = _cuts(total, size, off)
        return [b - a for a, b in zip(edges, edges[1:])]

    def key(off: int) -> tuple:
        rows = [pieces(off)] + ([pieces((off + size // 2) % size)] if stagger else [])
        smallest = min(min(r) for r in rows)
        whole = sum(r.count(size) for r in rows)
        return min(smallest, MIN_PIECE_CM), -sum(map(len, rows)), whole, smallest, -off
    return max(range(0, size, grid), key=key)


def _pack(pieces: list[tuple[int, int]], pw: int, ph: int) -> int:
    """Plaques entamées pour couper `pieces` (largeur, hauteur en cm, sens gardé) : premier emplacement libre, coupe en
    guillotine (bande à droite, bande en dessous). Approche simple et prudente : jamais moins de plaques qu'il n'en faut."""
    free: list[tuple[int, int]] = []
    boards = 0
    for w, h in sorted(pieces, key=lambda p: (p[1] * p[0], p[1]), reverse=True):
        spot = next((i for i, (fw, fh) in enumerate(free) if w <= fw and h <= fh), None)
        if spot is None:
            boards += 1
            fw, fh = pw, ph
        else:
            fw, fh = free.pop(spot)
        free += [r for r in ((fw - w, fh), (w, fh - h)) if r[0] > 0 and r[1] > 0]
    return boards


def plan(length_m: float, width_m: float, *, board_width: float = calc.DEFAULTS["board_width_m"],
         board_height: float = calc.DEFAULTS["board_height_m"], waste: float = calc.DEFAULTS["waste"]) -> dict:
    """Plan de pose d'un plafond rectangulaire L × l (m) : fourrures, tiges, plaques entières et coupées, et le dessin."""
    calc.check_inputs(positive={"longueur": length_m, "largeur": width_m, "largeur de plaque": board_width,
                                "hauteur de plaque": board_height})
    if length_m * width_m > MAX_AREA_M2:
        raise PlanError(f"Plafond de plus de {MAX_AREA_M2} m² : fais un plan par pièce (plus lisible pour les ouvriers).")
    run, across = calc.ceiling_run(length_m, width_m)
    rows, hangers, furring_ml = calc.ceiling_layout(run, across)
    run_cm, across_cm = round(run * 100), round(across * 100)
    sp_cm = round(calc.DEFAULTS["furring_spacing_m"] * 100)
    pw, ph = round(min(board_width, board_height) * 100), round(max(board_width, board_height) * 100)
    lines = [k * sp_cm for k in range(rows - 1)] + [across_cm]   # fourrures : tous les 0,50 m, la dernière contre le mur
    per_line = calc.ceil_int(run / calc.DEFAULTS["hanger_spacing_m"]) + 1

    ys = _cuts(across_cm, ph, _offset(across_cm, ph, sp_cm, False))   # bouts de plaque sur une fourrure
    off = _offset(run_cm, pw, 10, True)
    tiles: list[tuple[int, int, int, int, bool]] = []   # x, y, largeur, hauteur (cm), entière ?
    for j, (y0, y1) in enumerate(zip(ys, ys[1:])):
        xs = _cuts(run_cm, pw, (off + pw // 2) % pw if j % 2 else off)   # une rangée sur deux décalée d'une demi-plaque
        tiles += [(a, y0, b - a, y1 - y0, b - a == pw and y1 - y0 == ph) for a, b in zip(xs, xs[1:])]
    full = sum(1 for t in tiles if t[4])
    cut = [(w, h) for _, _, w, h, whole in tiles if not whole]
    used = full + _pack(cut, pw, ph)
    area = round(length_m * width_m, 3)
    quote = calc.boards_needed(area, waste, board_width * board_height)
    bar = calc.BAR_TXT
    furring_bars = calc.ceil_int(furring_ml / calc.BAR_LENGTH_M)
    perimeter = round(2 * (run + across), 2)
    angle_bars = calc.ceil_int(perimeter / calc.BAR_LENGTH_M)
    h_cm = round(calc.DEFAULTS["hanger_spacing_m"] * 100)
    ties = [k * h_cm for k in range(per_line - 1)] + [run_cm]   # tiges : tous les 90 cm depuis le mur, la dernière contre l'autre mur
    ends = "bouts sur une fourrure" if ph % sp_cm == 0 else "bouts à reprendre sur une fourrure ajoutée"
    out = {
        "piece": [run, across], "fourrures": rows, "fourrures_sens": f"dans le sens des {_fmt(run)} m", "fourrure_ml": furring_ml,
        "barres_fourrure": furring_bars, "tiges": hangers, "tiges_par_fourrure": per_line, "cornieres": angle_bars,
        "plaque": f"{_len(pw / 100)} × {_len(ph / 100)} m", "plaques_entieres": full, "morceaux_coupes": len(cut),
        "plaques_utilisees": used, "plaques_devis": quote,
        "consignes": [
            f"Fourrures dans le sens des {_fmt(run)} m : une tous les {sp_cm} cm, la dernière contre le mur. "
            f"{rows} fourrures = {_fmt(furring_ml)} ml = {furring_bars} barres de {bar} m.",
            f"Tiges : une tous les {h_cm} cm sur chaque fourrure, la dernière contre le mur. {per_line} par fourrure = {hangers} tiges.",
            f"Plaques de {_len(ph / 100)} m en travers des fourrures, {ends}, joints décalés de {pw // 2} cm.",
            f"Plaques : {full} entières + {len(cut)} coupées = {used} plaques (devis : {quote}).",
            f"Cornières : périmètre {_fmt(perimeter)} ml = {angle_bars} barres de {bar} m.",
        ],
    }
    if used > quote:
        out["alerte"] = f"Ce plan consomme {used} plaques, le devis en prévoit {quote} : ajoute {used - quote} plaque(s)."
    out["svg"] = _svg(run_cm, across_cm, lines, ties, tiles, sp_cm, h_cm, [
        f"Fourrures tous les {sp_cm} cm · tiges tous les {h_cm} cm · plaques de {_len(ph / 100)} m en travers",
        f"{rows} fourrures ({furring_bars} barres de {bar} m) · {hangers} tiges · {angle_bars} cornières de {bar} m",
        f"{full} plaques entières + {len(cut)} coupées = {used} plaques (devis : {quote})"])
    return out


def _svg(run_cm: int, across_cm: int, lines: list[int], ties: list[int], tiles: list, sp_cm: int, h_cm: int,
         texts: list[str]) -> str:
    """Vue de dessus 900 × 680 : plaques entières en vert clair, coupées en cuivre clair, fourrures vertes, tiges en points,
    cotes 50 cm (fourrures) et 90 cm (tiges) au bord du plafond."""
    scale = min(760 / run_cm, 430 / across_cm)
    rw, rh = run_cm * scale, across_cm * scale
    x0, y0 = (900 - rw) / 2, 105 + (430 - rh) / 2
    run, across = run_cm / 100, across_cm / 100
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 680" font-family="Arial">',
         '<rect x="0" y="0" width="900" height="680" fill="#ffffff"/>',
         f'<text x="450" y="40" font-size="26" font-weight="bold" fill="{GREEN}" text-anchor="middle">'
         f'Plan de pose — plafond {_fmt(run)} × {_fmt(across)} m</text>',
         f'<text x="450" y="70" font-size="16" fill="{GREY}" text-anchor="middle">{texts[0]}</text>']
    labels = []
    for x, y, w, h, whole in tiles:
        p.append(f'<rect x="{x0 + x * scale:.1f}" y="{y0 + y * scale:.1f}" width="{w * scale:.1f}" height="{h * scale:.1f}" '
                 f'fill="{LIGHT if whole else CUT}" stroke="{GREY}" stroke-width="1"/>')
        if not whole and h * scale >= 16:   # cote de coupe en cm, pour l'ouvrier qui découpe
            txt = f"{w}×{h}" if w * scale >= 52 else (str(w) if w * scale >= 24 else "")
            if txt:
                labels.append(f'<text x="{x0 + (x + w / 2) * scale:.1f}" y="{y0 + (y + h / 2) * scale + 5:.1f}" font-size="13" '
                              f'font-weight="bold" fill="{COPPER}" text-anchor="middle">{txt}</text>')
    for y in lines:
        yy = y0 + y * scale
        p.append(f'<line x1="{x0:.1f}" y1="{yy:.1f}" x2="{x0 + rw:.1f}" y2="{yy:.1f}" stroke="{GREEN}" stroke-width="2" '
                 f'stroke-dasharray="8 4"/>')
        p += [f'<circle cx="{x0 + x * scale:.1f}" cy="{yy:.1f}" r="3.5" fill="{INK}"/>' for x in ties]
    # cotes d'entraxe : 50 cm entre deux fourrures (à droite), 90 cm entre deux tiges (en bas)
    xr, yb = x0 + rw + 10, y0 + rh + 14
    y1 = y0 + min(sp_cm, across_cm) * scale
    x1 = x0 + min(h_cm, run_cm) * scale
    dims = [f'<path d="M{xr:.1f},{y0:.1f} V{y1:.1f} M{xr - 5:.1f},{y0:.1f} h10 M{xr - 5:.1f},{y1:.1f} h10" stroke="{COPPER}" stroke-width="2"/>',
            f'<text x="{xr + 8:.1f}" y="{(y0 + y1) / 2 + 5:.1f}" font-size="14" font-weight="bold" fill="{COPPER}">{sp_cm} cm</text>',
            f'<path d="M{x0:.1f},{yb:.1f} H{x1:.1f} M{x0:.1f},{yb - 5:.1f} v10 M{x1:.1f},{yb - 5:.1f} v10" stroke="{COPPER}" stroke-width="2"/>',
            f'<text x="{(x0 + x1) / 2:.1f}" y="{yb + 20:.1f}" font-size="14" font-weight="bold" fill="{COPPER}" text-anchor="middle">{h_cm} cm</text>']
    p += labels + dims + [
          f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rw:.1f}" height="{rh:.1f}" fill="none" stroke="{INK}" stroke-width="5"/>',
          f'<text x="{x0 + rw / 2:.1f}" y="{y0 - 12:.1f}" font-size="18" fill="{INK}" text-anchor="middle">{_fmt(run)} m</text>',
          f'<text x="{x0 - 12:.1f}" y="{y0 + rh / 2:.1f}" font-size="18" fill="{INK}" text-anchor="end">{_fmt(across)} m</text>',
          f'<text x="450" y="605" font-size="16" fill="{INK}" text-anchor="middle">{texts[1]}</text>',
          f'<text x="450" y="630" font-size="16" font-weight="bold" fill="{INK}" text-anchor="middle">{texts[2]}</text>',
          f'<text x="450" y="660" font-size="13" fill="{GREY}" text-anchor="middle">Tirets verts : fourrures · points : tiges · '
          f'vert clair : plaque entière · cuivre : coupe (cm) — UniC Plaquiste</text>',
          '</svg>']
    return "".join(p)
