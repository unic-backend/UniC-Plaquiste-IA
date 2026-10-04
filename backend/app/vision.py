"""Vision Claude : lire une photo, un plan scanné ou une page sans texte. Vide si Claude est indisponible."""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger("unic.vision")

MAX_SIDE = 1568  # au-delà, Claude réduit l'image lui-même : on économise l'envoi
MAX_PDF_PAGES = 6  # pages scannées lues par vision par PDF (coût borné)

PROMPT = (
    "Tu lis un document ou une photo pour un plaquiste (faux plafonds, cloisons, BA13) à Dakar.\n"
    "Transcris fidèlement, en français, sans rien inventer :\n"
    "1. Type : plan, croquis, photo de chantier, devis, facture, autre.\n"
    "2. Tout le texte lisible, cotes et unités incluses (L, l, h, surface, échelle).\n"
    "3. Pièces ou zones avec leurs dimensions, une ligne par pièce.\n"
    "4. Si les dimensions permettent de déduire une surface, donne le calcul (L × l = m²). Jamais de valeur non lisible.\n"
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
    res = ClaudeAIProvider().complete([{"role": "user", "content": content}], max_tokens=2000)
    return res.text.strip() if res.available else ""


def describe_image(path: Path) -> str:
    """Description + texte + cotes d'une image. Chaîne vide si vision impossible."""
    if not disponible():
        return ""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return _ask(_jpeg_b64(img))
    except Exception as exc:
        logger.debug("Vision image impossible : %s", exc)
        return ""


def describe_pdf_page(path: Path, index: int) -> str:
    """Même lecture pour une page PDF sans texte (plan scanné)."""
    if not disponible():
        return ""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            return _ask(_jpeg_b64(pdf[index].render(scale=2).to_pil()))
        finally:
            pdf.close()
    except Exception as exc:
        logger.debug("Vision PDF impossible : %s", exc)
        return ""
