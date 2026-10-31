"""Montage des vraies vidéos (scènes « clip ») : le moteur TRAVAILLE le film, il ne se contente pas de le recadrer.

- ffmpeg (make.py) : vitesse (ralenti, accéléré), étalonnage des couleurs, cadrage sur le sujet, arrêt sur image, écran partagé avant/après.
- image par image (compose.py) : zoom (avant, arrière, coup de zoom) en caméra sous-pixel, transitions entre plans (fondu, coupe franche, flash, glissé).

Fonctions pures, testées sans rendu. Les valeurs arrivent déjà validées par spec.py (scénario non fiable : jamais utilisé tel quel ici).
"""
from __future__ import annotations

# Étalonnages (noms validés par spec.GRADES) : filtres ffmpeg standards, rien à installer.
GRADE_VF = {
    "cinema": "eq=contrast=1.10:saturation=1.18:gamma=0.97,colorbalance=rs=0.04:gs=0.01:bs=-0.04:rh=0.03:bh=-0.03,vignette=PI/4.5",
    "warm": "eq=contrast=1.05:saturation=1.15,colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.05:bm=-0.05",
    "night": "eq=brightness=0.05:gamma=1.15:saturation=1.08,colorbalance=bs=0.06:bm=0.04:rh=0.02",
    "crisp": "unsharp=5:5:0.8:5:5:0.0,eq=contrast=1.06:saturation=1.10",
    "bw": "hue=s=0,eq=contrast=1.15",
}
DIVIDER = "0xF2C230"                     # trait doré entre les deux moitiés d'un écran partagé
FADE_S, FLASH_S, SLIDE_S = 0.35, 0.25, 0.40
PUNCH_AT, PUNCH_S = 0.35, 0.18          # coup de zoom : à 35 % du plan, en 0,18 s


def ease(p: float) -> float:
    """Accélère puis freine (pas de mouvement mécanique)."""
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def focus(sc: dict) -> tuple[float, float]:
    f = sc.get("focus") or {}
    return float(f.get("x", 0.5)), float(f.get("y", 0.5))


def play_seconds(sc: dict) -> float:
    """Temps où le film défile (le reste : arrêt sur la dernière image)."""
    return max(0.5, float(sc["seconds"]) - float(sc.get("freeze") or 0))


def _fit(w: int, h: int, fx: float, fy: float, speed: float, fps: int) -> str:
    """Un film mis au format : vitesse, cadence, couverture du cadre, cadrage sur le point (fx, fy) du film."""
    pts = f"setpts=(PTS-STARTPTS)/{speed:g}" if speed != 1 else "setpts=PTS-STARTPTS"
    return (f"{pts},fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h}:(iw-{w})*{fx:g}:(ih-{h})*{fy:g}")


def ffmpeg_args(sc: dict, src, src2, ow: int, oh: int, fps: int, n: int, pattern: str) -> list[str]:
    """Commande ffmpeg qui sort les n images JPEG du plan monté (vitesse, couleurs, cadrage, arrêt sur image, écran partagé)."""
    speed = float(sc.get("speed") or 1)
    fx, fy = focus(sc)
    need = f"{play_seconds(sc) * speed:.3f}"            # durée lue dans le fichier source
    grade = GRADE_VF.get(sc.get("grade") or "", "")
    tail = (f",{grade}" if grade else "") + f",tpad=stop_mode=clone:stop_duration={float(sc['seconds']):g}"
    args = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{float(sc.get('start') or 0):g}", "-t", need, "-i", str(src)]
    split = sc.get("split")
    if split and src2:
        hw = ow // 4 * 2                               # moitié gauche (paire), la droite prend le reste
        args += ["-ss", f"{float(split.get('start') or 0):g}", "-t", need, "-i", str(src2), "-filter_complex",
                 f"[0:v]{_fit(hw, oh, fx, fy, speed, fps)}[a];[1:v]{_fit(ow - hw, oh, fx, fy, speed, fps)}[b];"
                 f"[a][b]hstack=inputs=2,drawbox=x={hw - 4}:y=0:w=8:h={oh}:color={DIVIDER}@1:t=fill{tail}[v]", "-map", "[v]"]
    else:
        args += ["-vf", _fit(ow, oh, fx, fy, speed, fps) + tail]
    return args + ["-an", "-frames:v", str(n), "-q:v", "2", "-start_number", "0", str(pattern)]


def zoom_factor(sc: dict, f: int, frames: int, fps: int) -> float:
    mode, a = sc.get("zoom"), float(sc.get("zoom_amount") or 1.2)
    if mode == "in":
        return 1 + (a - 1) * ease(f / max(1, frames - 1))
    if mode == "out":
        return a - (a - 1) * ease(f / max(1, frames - 1))
    if mode == "punch":
        return 1 + (a - 1) * ease((f / fps - PUNCH_AT * frames / fps) / PUNCH_S)
    return 1.0


def zoom_box(sc: dict, f: int, frames: int, fps: int, w: int, h: int) -> tuple[float, float, float, float] | None:
    """Fenêtre (sous-pixel) à agrandir pour l'image f, centrée sur le point de cadrage ; None sans zoom."""
    z = zoom_factor(sc, f, frames, fps)
    if z <= 1.0005:
        return None
    fx, fy = focus(sc)
    cw, ch = w / z, h / z
    x0, y0 = (w - cw) * fx, (h - ch) * fy
    return (x0, y0, x0 + cw, y0 + ch)


def mix(sc: dict, nxt: dict | None, f: int, frames: int, fps: int, has_prev: bool) -> dict:
    """Transitions du plan pour l'image f : {dark: part d'image face au fond (1 = image pure), white: idem face au blanc (flash),
    slide: avancée du glissé (None = pas de glissé)}. « transition » dit comment le plan ENTRE ; il ne s'assombrit en sortie
    que si le plan suivant entre en fondu (ou n'est pas un film)."""
    tr = sc.get("transition") or "fade"
    if tr == "slide" and not has_prev:                   # rien à pousser (début de vidéo ou de tronçon) : fondu
        tr = "fade"
    fade_n = max(1, round(FADE_S * fps))
    out_fade = not (nxt and nxt.get("kind") == "clip" and (nxt.get("transition") or "fade") != "fade")
    dark = 1.0
    if tr == "fade":
        dark = min(dark, f / fade_n)
    if out_fade:
        dark = min(dark, (frames - 1 - f) / fade_n)
    white, slide = 1.0, None
    if tr == "flash":
        white = min(1.0, f / max(1, round(FLASH_S * fps)))
    if tr == "slide":
        n = max(1, round(SLIDE_S * fps))
        slide = ease(f / n) if f < n else None
    return {"dark": max(0.0, dark), "white": white, "slide": slide}
