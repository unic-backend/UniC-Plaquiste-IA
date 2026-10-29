"""Plan de pose d'un faux plafond (calepinage) DESSINÉ pour les ouvriers : où passent les fourrures, où vont les tiges, comment
poser les plaques.

Mêmes règles que le moteur de calcul (calc.ceiling_run / ceiling_layout) : fourrures dans le sens qui demande le moins de tiges,
tous les 0,50 m (la dernière contre le mur), tiges tous les 0,90 m au plus ; les nombres du plan sont ceux du devis.
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
    sens = "dans le sens de la longueur" if run >= across else "dans le sens de la largeur"
    out = {
        "piece": [run, across], "fourrures": rows, "fourrures_sens": sens, "fourrure_ml": furring_ml, "tiges": hangers,
        "tiges_par_fourrure": per_line, "plaques_entieres": full, "morceaux_coupes": len(cut), "plaques_utilisees": used,
        "plaques_devis": quote,
        "consignes": [
            f"Fourrures {sens}, tous les {f'{sp_cm / 100:.2f}'.replace('.', ',')} m ({rows} lignes, la dernière contre le mur).",
            f"{per_line} tiges par fourrure, une tous les {_fmt(run / (per_line - 1))} m ({hangers} tiges).",
            f"Plaques en travers des fourrures, bouts {'sur une fourrure' if ph % sp_cm == 0 else 'à reprendre sur une fourrure ajoutée'} ; "
            f"joints décalés de {_fmt(pw / 200)} m d'une rangée à l'autre.",
            f"{full} plaques entières, {len(cut)} morceaux coupés : {used} plaques consommées (devis : {quote}).",
        ],
    }
    if used > quote:
        out["alerte"] = f"Ce plan consomme {used} plaques, le devis en prévoit {quote} : ajoute {used - quote} plaque(s)."
    out["svg"] = _svg(run_cm, across_cm, lines, per_line, tiles, out)
    return out


def _svg(run_cm: int, across_cm: int, lines: list[int], per_line: int, tiles: list, info: dict) -> str:
    """Vue de dessus 900 × 680 : plaques entières en vert clair, coupées en cuivre clair, fourrures vertes, tiges en points."""
    scale = min(760 / run_cm, 440 / across_cm)
    rw, rh = run_cm * scale, across_cm * scale
    x0, y0 = (900 - rw) / 2, 110 + (440 - rh) / 2
    run, across = run_cm / 100, across_cm / 100
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 680" font-family="Arial">',
         '<rect x="0" y="0" width="900" height="680" fill="#ffffff"/>',
         f'<text x="450" y="40" font-size="26" font-weight="bold" fill="{GREEN}" text-anchor="middle">'
         f'Plan de pose — plafond {_fmt(run)} × {_fmt(across)} m</text>',
         f'<text x="450" y="70" font-size="15" fill="{GREY}" text-anchor="middle">{info["consignes"][0]}</text>']
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
        for k in range(per_line):
            p.append(f'<circle cx="{x0 + rw * k / (per_line - 1):.1f}" cy="{yy:.1f}" r="3.5" fill="{INK}"/>')
    p += labels + [
          f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rw:.1f}" height="{rh:.1f}" fill="none" stroke="{INK}" stroke-width="5"/>',
          f'<text x="{x0 + rw / 2:.1f}" y="{y0 - 12:.1f}" font-size="18" fill="{INK}" text-anchor="middle">{_fmt(run)} m</text>',
          f'<text x="{x0 - 12:.1f}" y="{y0 + rh / 2:.1f}" font-size="18" fill="{INK}" text-anchor="end">{_fmt(across)} m</text>',
          f'<text x="450" y="600" font-size="15" fill="{INK}" text-anchor="middle">{info["consignes"][1]}</text>',
          f'<text x="450" y="624" font-size="15" fill="{INK}" text-anchor="middle">{info["consignes"][3]}</text>',
          f'<text x="450" y="652" font-size="13" fill="{GREY}" text-anchor="middle">Tirets verts : fourrures · points : tiges · '
          f'vert clair : plaque entière · cuivre : coupe (cm) — UniC Plaquiste</text>',
          '</svg>']
    return "".join(p)
