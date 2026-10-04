"""Travail lourd sur PDF dans un PROCESSUS SÉPARÉ, à mémoire bornée.

Un plan d'architecte de 2 Mo peut contenir des centaines de milliers de traits : le dessiner coûte des centaines de Mo.
Fait ici, la mémoire est rendue au système dès la fin, et un plan trop lourd tue ce processus, jamais le serveur.
Usage : python pdfworker.py '<json>' → JSON sur la sortie standard. Aucune dépendance au reste de l'application.
"""
import base64
import gc
import io
import json
import sys


def _open(path):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(path)


def _scale(page, wanted, max_side):
    w, h = page.get_size()
    return max(0.2, min(wanted, max_side / max(w, h, 1)))


def op_text(path, max_pages=2000):
    doc = _open(path)
    out = []
    try:
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            try:
                w, h = page.get_size()
                tp = page.get_textpage()
                try:
                    out.append({"t": (tp.get_text_range() or "").replace("\x00", " "), "w": float(w), "h": float(h)})
                finally:
                    tp.close()
            finally:
                page.close()
        return {"total": len(doc), "pages": out}
    finally:
        doc.close()


def op_images(path, pages, max_side=1568, quality=85):
    doc = _open(path)
    out = []
    try:
        for i in pages:
            if i >= len(doc):
                continue
            page = doc[i]
            try:
                img = page.render(scale=_scale(page, 2, max_side)).to_pil().convert("RGB")
            finally:
                page.close()
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            del img
            gc.collect()
            out.append(base64.b64encode(buf.getvalue()).decode())
        return {"images": out}
    finally:
        doc.close()


def op_ocr(path, index, max_side=3000, lang="fra+eng"):
    import pytesseract
    doc = _open(path)
    try:
        page = doc[index]
        try:
            img = page.render(scale=_scale(page, 300 / 72, max_side)).to_pil()
        finally:
            page.close()
    finally:
        doc.close()
    return {"text": pytesseract.image_to_string(img, lang=lang).strip()}


OPS = {"text": op_text, "images": op_images, "ocr": op_ocr}

if __name__ == "__main__":
    req = json.loads(sys.argv[1])
    try:
        res = OPS[req.pop("op")](**req)
    except MemoryError:
        res = {"error": "memory"}
    except Exception as exc:   # noqa: BLE001 — renvoyé au serveur, jamais d'exception non gérée
        res = {"error": type(exc).__name__}
    sys.stdout.write(json.dumps(res))
