"""Extraire un tracé d'encre (signature, cachet) d'une photo prise au téléphone : papier blanc, table sombre, lumière faible.

Méthode : teinte locale du papier (flou large) ; encre = pixel nettement plus sombre que le papier autour ; on ignore la table
(zone sombre) et le bord du papier ; recadrage sur l'essentiel de l'encre (les petites taches isolées sont écartées).
Résultat : PNG transparent, encre bleu foncé uniforme (nette à l'impression).
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter, ImageOps

INK = (31, 58, 147, 255)
MAX_SIDE = 1400


class InkError(Exception):
    pass


def _otsu(x: np.ndarray) -> int:
    h, _ = np.histogram(x, 256, (0, 256))
    p = h / max(1, h.sum())
    w = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        s = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    return int(np.nanargmax(s))


def load(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise InkError("Image illisible : envoie une photo ou une capture.") from exc
    try:
        img = ImageOps.exif_transpose(img)   # certaines photos ont des données EXIF abîmées : on garde l'image telle quelle
    except Exception:
        pass
    return img


def extract(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        flat = Image.new("RGB", img.size, "white")   # image déjà transparente : fond blanc
        flat.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = flat
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    gray = img.convert("L")
    lum = np.asarray(gray).astype(float)
    paper_tone = np.asarray(gray.filter(ImageFilter.GaussianBlur(28))).astype(float)
    paper = paper_tone > _otsu(paper_tone) if paper_tone.std() > 18 else np.ones_like(lum, dtype=bool)
    paper = np.asarray(Image.fromarray((paper * 255).astype("uint8")).filter(ImageFilter.MinFilter(31))) > 0
    rgb = np.asarray(img).astype(float)
    reddish = rgb[..., 0] > rgb[..., 2] + 40   # annotations au feutre rouge ajoutées sur la capture : pas de l'encre du cachet
    ink = (lum < paper_tone * 0.80) & paper & ~reddish
    mask = Image.fromarray((ink * 255).astype("uint8")).filter(ImageFilter.MedianFilter(3))
    m = np.asarray(mask) > 0
    ys, xs = np.nonzero(m)
    if len(xs) < 200:
        raise InkError("Aucun tracé trouvé : photographie en pleine lumière, encre foncée sur papier blanc.")
    x0, x1 = np.percentile(xs, [0.7, 99.3]).astype(int)
    y0, y1 = np.percentile(ys, [0.7, 99.3]).astype(int)
    pad = int(0.03 * max(x1 - x0, y1 - y0)) + 2
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(m.shape[1], x1 + pad), min(m.shape[0], y1 + pad)
    out = Image.new("RGBA", img.size, INK)
    out.putalpha(mask)
    return out.crop((x0, y0, x1, y1))
