"""Outils PDF : fusionner, extraire des pages (découper), alléger. Toujours sur une COPIE : l'original reste intact."""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

from app.config import settings
from app.models import StoredFile, new_id
from app.services import store_artifact

MAX_FILES = 20
MAX_PAGES = 800


class PdfToolError(ValueError):
    pass


def _rec(db: Session, ref: str) -> StoredFile:
    """Un fichier par identifiant, sinon par nom (sans accents ni casse) ; plusieurs candidats = on demande lequel."""
    ref = (ref or "").strip()
    rec = db.get(StoredFile, ref) if ref else None
    if rec is None and ref:
        low = ref.lower()
        hits = [r for r in db.query(StoredFile).order_by(StoredFile.id.desc()).limit(300).all() if low in (r.filename or "").lower()]
        if len(hits) > 1:
            raise PdfToolError("Plusieurs fichiers correspondent : " + " ; ".join(h.filename for h in hits[:6]) + ". Lequel ?")
        rec = hits[0] if hits else None
    if rec is None:
        raise PdfToolError(f"Fichier introuvable : « {ref} ». Demande au patron de le joindre, ou lis list_files.")
    if not Path(rec.path).exists() or not (rec.filename or "").lower().endswith(".pdf"):
        raise PdfToolError(f"« {rec.filename} » n'est pas un PDF lisible.")
    return rec


def _reader(rec: StoredFile) -> PdfReader:
    try:
        r = PdfReader(rec.path)
        if r.is_encrypted:
            raise PdfToolError(f"« {rec.filename} » est protégé par un mot de passe.")
        return r
    except PdfToolError:
        raise
    except Exception as exc:
        raise PdfToolError(f"« {rec.filename} » est un PDF abîmé ({type(exc).__name__}).") from exc


def parse_pages(spec: str, total: int) -> list[int]:
    """« 1-3,5,8- » → index 0-based, dans l'ordre demandé, sans doublon."""
    out: list[int] = []
    for part in re.split(r"[,;\s]+", (spec or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?-(\d+)?|(\d+)", part)
        if not m:
            raise PdfToolError(f"Pages illisibles : « {part} ». Exemple : 1-3,5,8-")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or total)
        if a < 1 or b > total or a > b:
            raise PdfToolError(f"Pages hors du document ({total} pages) : « {part} ».")
        out += [i - 1 for i in range(a, b + 1) if i - 1 not in out]
    if not out:
        raise PdfToolError("Donne les pages voulues, par exemple 1-3,5.")
    return out


def _save(db: Session, writer: PdfWriter, name: str, src_id: str, user_id: str | None) -> dict:
    folder = settings.artifacts_path / "pdftools"
    folder.mkdir(parents=True, exist_ok=True)
    key = new_id()[:8]
    stem = re.sub(r"[^\w\-]+", "_", name).strip("_")[:50] or "document"
    out = folder / f"{stem}_{key}.pdf"
    with open(out, "wb") as fh:
        writer.write(fh)
    art = store_artifact(db, out, f"{name}.pdf", "pdf_tool", src_id, f"pdftool-{key}", user_id)
    db.commit()
    return {"id": art.id, "filename": art.filename, "mime": "application/pdf", "size": art.size}


def info(db: Session, ref: str) -> dict:
    rec = _rec(db, ref)
    return {"fichier": rec.filename, "pages": len(_reader(rec).pages), "taille_ko": round((rec.size or 0) / 1024)}


def merge(db: Session, refs: list[str], user_id: str | None) -> dict:
    if not 2 <= len(refs) <= MAX_FILES:
        raise PdfToolError(f"Donne de 2 à {MAX_FILES} PDF à fusionner, dans l'ordre voulu.")
    recs = [_rec(db, r) for r in refs]
    w, total = PdfWriter(), 0
    for rec in recs:
        rd = _reader(rec)
        total += len(rd.pages)
        if total > MAX_PAGES:
            raise PdfToolError(f"Trop de pages au total ({MAX_PAGES} au plus).")
        for p in rd.pages:
            w.add_page(p)
    art = _save(db, w, "Fusion de " + " + ".join(Path(r.filename).stem[:20] for r in recs[:3]) + (" …" if len(recs) > 3 else ""), recs[0].id, user_id)
    return {"ok": True, "artifact": art, "pages": total, "note": f"{len(recs)} PDF fusionnés dans l'ordre donné. Les originaux sont intacts."}


def extract(db: Session, ref: str, pages: str, user_id: str | None) -> dict:
    rec = _rec(db, ref)
    rd = _reader(rec)
    idx = parse_pages(pages, len(rd.pages))
    w = PdfWriter()
    for i in idx:
        w.add_page(rd.pages[i])
    art = _save(db, w, f"{Path(rec.filename).stem[:40]} (pages {pages.strip()})", rec.id, user_id)
    return {"ok": True, "artifact": art, "pages": len(idx), "note": "Nouveau PDF avec ces pages. L'original est intact."}


def compress(db: Session, ref: str, user_id: str | None) -> dict:
    """Allègement SANS perte (flux compressés, objets identiques fusionnés) : le texte reste sélectionnable, les images ne sont pas dégradées."""
    rec = _rec(db, ref)
    rd = _reader(rec)
    w = PdfWriter()
    for p in rd.pages:
        w.add_page(p)
    for p in w.pages:
        p.compress_content_streams()
    w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    art = _save(db, w, f"{Path(rec.filename).stem[:40]} (allégé)", rec.id, user_id)
    before, after = rec.size or 0, art["size"]
    gain = round(100 * (before - after) / before) if before else 0
    note = ("Allégé sans perte de qualité." if gain > 0 else "Ce PDF est déjà optimisé : pas de gain sans dégrader les images.")
    return {"ok": True, "artifact": art, "avant_ko": round(before / 1024), "apres_ko": round(after / 1024), "gain_pct": max(0, gain), "note": note}
