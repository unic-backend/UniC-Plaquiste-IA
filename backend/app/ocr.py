"""OCR optionnel : lire une page scannée ou une image, ou se taire.

Jamais de texte inventé : sans Tesseract, l'OCR rend une chaîne vide et le
système dit « NON DISPONIBLE ».
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("unic.ocr")

LANGUES_VOULUES = ("fra", "eng")
OCR_MAX_SIDE = 3000   # 5000 px : 66 s et 400 Mo sur un plan A1 ; 3000 px : 1 s et 110 Mo
ECHELLE_RENDU = 300 / 72  # 300 DPI : en dessous, un A4 scanné devient illisible


@lru_cache(maxsize=1)
def langues() -> str | None:
    """Langues Tesseract réellement installées (fra/eng), ou None si OCR impossible."""
    try:
        import pytesseract

        installees = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # binaire absent ou module non installé
        logger.debug("OCR indisponible : %s", exc)
        return None
    voulues = [lg for lg in LANGUES_VOULUES if lg in installees]
    return "+".join(voulues) if voulues else None


def disponible() -> bool:
    return langues() is not None


def scale_for(page, wanted: float, max_side: int) -> float:
    """Échelle de rendu bornée : un plan A1/A0 à 300 DPI ferait 200 Mo en mémoire et planterait le serveur (512 Mo)."""
    try:
        w, h = page.get_size()
        return max(0.2, min(wanted, max_side / max(w, h, 1)))
    except Exception:
        return min(wanted, 1.5)


def ocr_pdf_page(path: Path, index: int) -> str:
    """Texte d'une page PDF sans calque texte. Vide si OCR impossible."""
    lang = langues()
    if lang is None:
        return ""
    doc = None
    try:
        import pypdfium2 as pdfium
        import pytesseract

        doc = pdfium.PdfDocument(str(path))
        page = doc[index]
        image = page.render(scale=scale_for(page, ECHELLE_RENDU, OCR_MAX_SIDE)).to_pil()
        return pytesseract.image_to_string(image, lang=lang).strip()
    except Exception as exc:
        logger.debug("OCR page %s impossible : %s", index + 1, exc)
        return ""
    finally:
        if doc is not None:
            doc.close()


def ocr_image(path: Path) -> str:
    """Texte d'une image (photo de plan, cotes, facture). Vide si OCR impossible."""
    lang = langues()
    if lang is None:
        return ""
    try:
        import pytesseract
        from PIL import Image

        with Image.open(path) as img:
            return pytesseract.image_to_string(img, lang=lang).strip()
    except Exception as exc:
        logger.debug("OCR image impossible : %s", exc)
        return ""
