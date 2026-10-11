"""Vision Claude : lire une photo, un plan scanné ou une page sans texte. Vide si Claude est indisponible."""
from __future__ import annotations

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import settings

logger = logging.getLogger("unic.vision")

MAX_SIDE = 1568  # au-delà, Claude réduit l'image lui-même : on économise l'envoi
MAX_PDF_PAGES = 6  # pages scannées lues par vision par PDF (coût borné)
TILE_RATIO = 1.5   # image plus allongée que ça (capture de téléphone d'un devis) : lue par tranches, sinon le texte devient minuscule
MAX_TILES = 4      # coût borné
OVERLAP = 0.08     # recouvrement entre tranches : une ligne coupée reste lisible

PROMPT = (
    "Le document peut être en français ou en anglais (ceiling, partition, drywall, bedroom…) : transcris dans la langue d'origine et traduis en français.\n"
    "Tu lis un document ou une photo pour un plaquiste (faux plafonds, cloisons, BA13) à Dakar.\n"
    "Transcris fidèlement, en français, sans rien inventer :\n"
    "1. Type : plan, croquis, photo de chantier, devis, facture, autre.\n"
    "2. Tout le texte lisible, cotes et unités incluses (L, l, h, surface, échelle).\n"
    "3. Pièces ou zones avec leurs dimensions, une ligne par pièce.\n"
    "4. Tableau (devis, facture, liste de matériaux) : une ligne par ligne du tableau, colonnes séparées par « | », quantités et unités exactes.\n"
    "5. Si les dimensions permettent de déduire une surface, donne le calcul (L × l = m²). Jamais de valeur non lisible.\n"
    "Ce qui est illisible ou incertain : écris « illisible » ou « à confirmer ». Pas d'introduction."
)


def disponible() -> bool:
    return bool(settings.anthropic_api_key)


def _jpeg_b64(img) -> str:
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _ask(b64: str) -> str:
    from app.ai import ClaudeAIProvider

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": PROMPT},
    ]
    res = ClaudeAIProvider().complete([{"role": "user", "content": content}], max_tokens=2000,
                                      model=settings.anthropic_fast_model)
    return res.text.strip() if res.available else ""


def tiles(img) -> list:
    """Image très allongée (capture d'un devis) : tranches qui se recouvrent, chacune lue à pleine taille.
    Image normale : inchangée. Au plus MAX_TILES tranches."""
    w, h = img.size
    long_, short = max(w, h), min(w, h)
    if short == 0 or long_ / short <= TILE_RATIO:
        return [img]
    n = min(MAX_TILES, max(2, round(long_ / (short * TILE_RATIO)) + 1))
    step = long_ / n
    pad = int(step * OVERLAP)
    out = []
    for i in range(n):
        a, b = max(0, int(i * step) - pad), min(long_, int((i + 1) * step) + pad)
        out.append(img.crop((0, a, w, b)) if h >= w else img.crop((a, 0, b, h)))
    return out


def describe_image(path: Path) -> str:
    """Description + texte + cotes d'une image. Chaîne vide si vision impossible."""
    if not disponible():
        return ""
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as img:
            try:
                img = ImageOps.exif_transpose(img) or img   # photo prise en travers : à l'endroit avant lecture
            except Exception:
                pass
            parts = tiles(img)
            payloads = [_jpeg_b64(t) for t in parts]
        if len(payloads) > 1:   # tranches lues en même temps : le délai d'attente ne s'additionne plus
            with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
                texts = list(pool.map(_ask, payloads))
        else:
            texts = [_ask(payloads[0])]
        if len(parts) > 1:
            return "\n\n".join(f"[Partie {i + 1}/{len(parts)}]\n{t}" for i, t in enumerate(texts) if t)
        return texts[0] if texts else ""
    except Exception as exc:
        logger.warning("Vision image impossible : %s", exc)   # visible dans le journal : sans ça l'IA « devient aveugle » en silence
        return ""


def describe_pdf_page(path: Path, index: int) -> str:
    """Même lecture pour une page PDF sans texte (plan scanné)."""
    if not disponible():
        return ""
    try:
        from app import pdfjob
        images = pdfjob.run("images", timeout=60, path=str(path), pages=[index], max_side=MAX_SIDE)["images"]
        return _ask(images[0]) if images else ""
    except Exception as exc:
        logger.debug("Vision PDF impossible : %s", exc)
        return ""
