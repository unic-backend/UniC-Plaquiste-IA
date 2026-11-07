"""Réponse EN PHOTO : les repères donnés par l'IA (zones en fractions de l'image) sont dessinés sur l'image regardée — plan, coffret
électrique, climatiseur — avec un numéro par repère et une légende en bas, couleur selon la gravité. Le dessin est fait en code :
l'IA ne fabrique pas l'image, elle désigne seulement où regarder."""
from __future__ import annotations

import base64
import io
import textwrap

from PIL import Image, ImageDraw, ImageFont

COLORS = {"danger": (211, 47, 47), "defaut": (239, 108, 0), "a_verifier": (230, 160, 0), "ok": (46, 125, 50), "info": (21, 101, 192)}
LABELS = {"danger": "danger", "defaut": "défaut", "a_verifier": "à vérifier", "ok": "conforme", "info": "repère"}
MAX_MARKS = 12
MIN_SIDE = 1100   # image agrandie au besoin : numéros et légende lisibles au téléphone


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def clean(raw) -> list[dict]:
    """Repères valides seulement : zone de 4 fractions remises dans l'image, titre court, gravité connue ; au plus 12."""
    out = []
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(r, dict):
            continue
        try:
            x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in r.get("zone") or [])
        except (TypeError, ValueError):
            continue
        x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        if x1 - x0 < 0.005 or y1 - y0 < 0.005:
            continue
        grav = r.get("gravite") if r.get("gravite") in COLORS else "info"
        title = " ".join(str(r.get("titre") or "").split())[:70] or f"Repère {i + 1}"
        page = r.get("page")
        out.append({"n": len(out) + 1, "zone": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)], "titre": title, "gravite": grav,
                    **({"page": int(page)} if isinstance(page, (int, float)) else {})})
        if len(out) == MAX_MARKS:
            break
    return out


def draw(image_b64: str, marks: list[dict], title: str = "") -> bytes:
    """PNG : l'image avec un cadre numéroté par repère, puis la légende (numéro, gravité, titre)."""
    img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
    if max(img.size) < MIN_SIDE:
        k = MIN_SIDE / max(img.size)
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    W, H = img.size
    unit = max(W, H) / 1000
    stroke, badge, fs = max(3, round(4 * unit)), round(20 * unit), round(18 * unit)
    font, small = _font(fs), _font(round(fs * 0.9))
    d = ImageDraw.Draw(img)
    for m in marks:
        x0, y0, x1, y1 = m["zone"]
        box = (x0 * W, y0 * H, x1 * W, y1 * H)
        col = COLORS[m["gravite"]]
        d.rectangle(box, outline=(255, 255, 255), width=stroke + 4)   # liseré blanc : visible sur fond sombre comme clair
        d.rectangle(box, outline=col, width=stroke)
        cx, cy = min(max(box[0], badge), W - badge), min(max(box[1], badge), H - badge)
        d.ellipse((cx - badge, cy - badge, cx + badge, cy + badge), fill=col, outline=(255, 255, 255), width=max(2, stroke // 2))
        d.text((cx, cy), str(m["n"]), fill=(255, 255, 255), font=font, anchor="mm")
    lines = [f"{m['n']}. [{LABELS[m['gravite']]}] {m['titre']}" for m in marks]
    wrap = max(30, int(W / (fs * 0.55)))
    rows = [(i, t) for i, line in enumerate(lines) for t in textwrap.wrap(line, wrap)]
    line_h = round(fs * 1.45)
    head = line_h if title else 0
    legend_h = head + line_h * len(rows) + round(24 * unit)
    out = Image.new("RGB", (W, H + legend_h), (255, 255, 255))
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    y = H + round(12 * unit)
    if title:
        d.text((round(16 * unit), y), title[:120], fill=(29, 35, 33), font=font)
        y += line_h
    for i, text in rows:
        d.text((round(16 * unit), y), text, fill=COLORS[marks[i]["gravite"]] if marks[i]["gravite"] != "a_verifier" else (150, 100, 0),
               font=small)
        y += line_h
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def store(db, png: bytes, title: str, user_id: str | None):
    """L'image annotée devient un fichier de la conversation (bouton Partager), comme les dessins."""
    import re

    from app.config import settings
    from app.models import new_id
    from app.services import store_artifact
    key = new_id()[:8]
    name = re.sub(r"[^\w\-]+", "_", title or "photo").strip("_")[:40] or "photo"
    folder = settings.artifacts_path / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"UniC_{name}_{key}.png"
    path.write_bytes(png)
    return store_artifact(db, path, path.name, "photo", key, f"unic-photo-{key}", user_id, mime="image/png")
