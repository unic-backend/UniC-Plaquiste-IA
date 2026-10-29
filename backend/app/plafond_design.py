"""Plafonds décoratifs proposés au client : des idées DESSINÉES (vue de dessus cotée) pour une pièce, avec les longueurs utiles.

Styles : caisson central (décaissé), gorge lumineuse périphérique (ruban LED caché), bandeau périphérique, îlot suspendu.
Les dessins sont générés en code (cotes exactes, calculées depuis les dimensions du patron, jamais inventées) puis rendus en PNG
partageable par diagrams.render. Longueurs de retombée et de ruban LED, surface des retombées : de la géométrie. Les plaques des
retombées suivent la règle des plaques du moteur (⌈ S × (1 + d) / Splaque ⌉). L'ossature des retombées reste à chiffrer : signalé.
"""
from __future__ import annotations

from app import calc

STYLES = {
    "caisson": ("Caisson central", "Un décaissé au centre de la pièce, encadré d'une retombée : il donne du volume et souligne le centre."),
    "gorge": ("Gorge lumineuse", "Un bandeau tout autour avec un ruban LED caché : lumière douce et indirecte sur le plafond."),
    "bandeau": ("Bandeau périphérique", "Un bandeau abaissé le long des murs pour encastrer des spots ; le centre reste plat et haut."),
    "ilot": ("Îlot suspendu", "Un îlot rectangulaire au-dessus de la zone principale (salon, table), éclairé par LED sur son pourtour."),
}
DEFAULT_STYLES = ("caisson", "gorge", "ilot")
GREEN, COPPER, LIGHT, INK = "#1f5e3b", "#b87333", "#e8f1ea", "#1d2321"


class DesignError(ValueError):
    pass


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def design(style: str, length_m: float, width_m: float, *, marge_m: float = 0.6, retombee_m: float = 0.15,
           waste: float = calc.DEFAULTS["waste"], board_m2: float = 2.4) -> dict:
    """Géométrie d'un style pour une pièce L × l (m) : rectangle intérieur, retombée, ruban LED, plaques des retombées."""
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
            "plaques_retombees": calc.boards_needed(area, waste, board_m2), "svg": _svg(style, name, L, W, marge, iw, ih, retombee_m, led)}


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


def designs(length_m: float, width_m: float, styles: list | None = None, **kw) -> list[dict]:
    chosen = [s for s in (styles or DEFAULT_STYLES) if s in STYLES][:4] or list(DEFAULT_STYLES)
    return [design(s, length_m, width_m, **kw) for s in chosen]
