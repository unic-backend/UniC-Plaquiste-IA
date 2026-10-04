"""Pipeline documents : extraction, classification, indexation. Pas d'envoi massif du PDF au modèle."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app import cad, ocr, vision
from app.config import settings
from app.models import DocumentChunk, ExtractedPage, StoredFile, utcnow, new_id

DIM_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:m|mm|cm)\b|"
    r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(?:m|mm)?",
    re.I,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_upload(data: bytes, filename: str, mime: str, user_id: str | None, project_id: str | None, db: Session) -> StoredFile:
    fid = new_id()
    ext = Path(filename).suffix.lower() or ""
    dest_dir = settings.uploads_path / fid[:2]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{fid}{ext}"
    dest.write_bytes(data)
    rec = StoredFile(
        id=fid,
        filename=filename,
        mime_type=mime or "application/octet-stream",
        path=str(dest),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        kind="upload",
        project_id=project_id,
        uploaded_by=user_id,
        processing_status="queued",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def classify_page(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"1\s*:\s*\d{2,4}|échelle|scale", t) or re.search(r"\b(plan|coupe|façade|elevation|niveau)\b", t):
        return "plan"
    if re.search(r"\b(devis|quotation|quote)\b", t):
        return "quotation"
    if re.search(r"\b(facture|invoice)\b", t):
        return "invoice"
    if re.search(r"\b(porte|door|fenêtre|window|cloison|partition)\b", t) and len(DIM_RE.findall(t)) >= 3:
        return "schedule"
    if len(t.strip()) < 40:
        return "scanned_or_empty"
    return "document"


def extract_pdf(file_rec: StoredFile, db: Session, max_pages: int = 2000) -> dict:
    path = Path(file_rec.path)
    reader = PdfReader(str(path))
    n = min(len(reader.pages), max_pages)
    file_rec.page_count = len(reader.pages)
    db.query(ExtractedPage).filter(ExtractedPage.file_id == file_rec.id).delete()
    db.query(DocumentChunk).filter(DocumentChunk.file_id == file_rec.id).delete()

    pages_out = []
    empty_pages = 0
    vision_pages = 0
    for i in range(n):
        page = reader.pages[i]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.replace("\x00", " ").strip()
        if len(text) < 20:
            text = ocr.ocr_pdf_page(path, i) or text
        if len(text) < 20 and vision_pages < vision.MAX_PDF_PAGES:
            vision_pages += 1
            seen = vision.describe_pdf_page(path, i)
            text = f"[Lecture visuelle IA] {seen}" if seen else text
        if len(text) < 20:
            empty_pages += 1
        box = page.mediabox
        width = float(box.width) if box else None
        height = float(box.height) if box else None
        klass = classify_page(text)
        rec = ExtractedPage(
            file_id=file_rec.id,
            page_number=i + 1,
            text=text,
            classification=klass,
            width=width,
            height=height,
        )
        db.add(rec)
        pages_out.append({"page": i + 1, "classification": klass, "chars": len(text)})
        for chunk in chunk_text(text, 900):
            db.add(DocumentChunk(file_id=file_rec.id, page_number=i + 1, text=chunk))

    ocr_needed = file_rec.page_count and empty_pages / max(n, 1) > 0.6
    file_rec.processing_status = "completed"
    if ocr_needed:
        file_rec.processing_status = "completed_no_ocr"
        file_rec.processing_error = (
            "La majorité des pages n'ont pas de calque texte. "
            + (
                "L'OCR n'a rien pu lire sur ces pages."
                if ocr.disponible() or vision.disponible()
                else "OCR et vision IA NON DISPONIBLES. Fournissez un PDF vectoriel."
            )
        )
    db.commit()
    return {
        "file_id": file_rec.id,
        "pages": file_rec.page_count,
        "processed": n,
        "empty_pages": empty_pages,
        "ocr_needed": ocr_needed,
        "status": file_rec.processing_status,
        "warning": file_rec.processing_error,
        "page_summaries": pages_out[:50],
    }


def chunk_text(text: str, size: int = 900) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = []
    buf = []
    n = 0
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if n + len(para) > size and buf:
            parts.append("\n".join(buf))
            buf, n = [para], len(para)
        else:
            buf.append(para)
            n += len(para)
    if buf:
        parts.append("\n".join(buf))
    return parts


def search_pages(db: Session, file_id: str, query: str, limit: int = 20) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if len(t) > 1]
    pages = (
        db.query(ExtractedPage)
        .filter(ExtractedPage.file_id == file_id)
        .order_by(ExtractedPage.page_number)
        .all()
    )
    scored = []
    for p in pages:
        blob = (p.text or "").lower()
        score = sum(blob.count(t) for t in tokens)
        if score:
            snippet = _snippet(p.text or "", tokens)
            scored.append({
                "page": p.page_number,
                "classification": p.classification,
                "score": score,
                "snippet": snippet,
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def extract_dimensions(text: str) -> list[str]:
    found = []
    for m in DIM_RE.finditer(text or ""):
        found.append(m.group(0))
    return found[:80]


def find_in_document(db: Session, file_id: str, topic: str) -> dict:
    topic_l = topic.lower()
    keywords_map = {
        "portes": ["porte", "door", "blk", "pe"],
        "doors": ["porte", "door"],
        "cloisons": ["cloison", "partition", "placo", "ba13", "doublage"],
        "partitions": ["cloison", "partition", "drywall"],
        "dimensions": ["dimension", "cote", "échelle", "1:", "mm", "m "],
        "quantités": ["quantit", "qté", "qty", "nbre", "nombre"],
        "quantities": ["quantit", "qty"],
    }
    keys = keywords_map.get(topic_l, [topic_l])
    pages = (
        db.query(ExtractedPage)
        .filter(ExtractedPage.file_id == file_id)
        .order_by(ExtractedPage.page_number)
        .all()
    )
    hits = []
    dims = []
    for p in pages:
        blob = (p.text or "").lower()
        if any(k in blob for k in keys):
            hits.append({
                "page": p.page_number,
                "classification": p.classification,
                "snippet": _snippet(p.text or "", keys),
                "dimensions": extract_dimensions(p.text or "")[:12],
            })
        dims.extend({"page": p.page_number, "value": d} for d in extract_dimensions(p.text or ""))
    return {
        "topic": topic,
        "hits": hits[:40],
        "hit_count": len(hits),
        "pages_with_hits": [h["page"] for h in hits],
        "dimensions_sample": dims[:40],
        "status": "ok" if hits else "none",
    }


def _snippet(text: str, tokens: list[str], radius: int = 140) -> str:
    low = text.lower()
    pos = -1
    for t in tokens:
        pos = low.find(t)
        if pos >= 0:
            break
    if pos < 0:
        return text[: radius * 2].replace("\n", " ")
    a = max(0, pos - radius)
    b = min(len(text), pos + radius)
    s = text[a:b].replace("\n", " ")
    if a > 0:
        s = "…" + s
    if b < len(text):
        s = s + "…"
    return s


def read_plaintext(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for name in wb.sheetnames[:12]:
        ws = wb[name]
        lines.append(f"# Feuille {name}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > 200:
                lines.append("… (tronqué)")
                break
            vals = ["" if v is None else str(v) for v in row]
            if any(vals):
                lines.append(" | ".join(vals))
    return "\n".join(lines)


def process_file(file_rec: StoredFile, db: Session) -> dict:
    # Déjà lu (à l'envoi du fichier) : on ne relit pas au moment du message. Évite doubles coûts OCR/vision et conflits de pages.
    if file_rec.processing_status in ("completed", "completed_no_ocr") and \
            db.query(ExtractedPage).filter(ExtractedPage.file_id == file_rec.id).first() is not None:
        return {"file_id": file_rec.id, "status": file_rec.processing_status, "pages": file_rec.page_count,
                "warning": file_rec.processing_error or None, "cached": True}
    db.query(ExtractedPage).filter(ExtractedPage.file_id == file_rec.id).delete()
    db.query(DocumentChunk).filter(DocumentChunk.file_id == file_rec.id).delete()
    path = Path(file_rec.path)
    mime = (file_rec.mime_type or "").lower()
    ext = path.suffix.lower()
    try:
        if ext == ".pdf" or "pdf" in mime:
            return extract_pdf(file_rec, db)
        text = ""
        if ext in {".txt", ".csv", ".md"}:
            text = read_plaintext(path)
        elif ext in {".docx"}:
            text = read_docx(path)
        elif ext in {".xlsx", ".xlsm"}:
            text = read_xlsx(path)
        elif ext in cad.CAD_EXT:
            text = cad.read_dxf(path) if ext == ".dxf" else cad.read_ifc(path)
        elif ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            file_rec.processing_status = "completed"
            file_rec.page_count = 1
            read = ocr.ocr_image(path)
            seen = vision.describe_image(path)
            if seen:
                read = f"[Lecture visuelle IA] {seen}" + (f"\n\n[OCR]\n{read}" if read else "")
            db.add(ExtractedPage(
                file_id=file_rec.id, page_number=1,
                text=read or "[Image] Aucun texte lu. Analyse visuelle NON DISPONIBLE sans IA vision.",
                classification=classify_page(read) if read else "photo",
            ))
            for chunk in chunk_text(read):
                db.add(DocumentChunk(file_id=file_rec.id, page_number=1, text=chunk))
            db.commit()
            return {
                "file_id": file_rec.id,
                "kind": "image",
                "status": "completed",
                "chars": len(read),
                "warning": None if read else (
                    "Image stockée. Aucun texte lu : "
                    + ("pas de texte détecté." if ocr.disponible() or vision.disponible() else "OCR et vision IA NON DISPONIBLES (clé Claude absente).")
                ),
            }
        else:
            file_rec.processing_status = "unsupported"
            file_rec.processing_error = cad.DWG_MESSAGE if ext == ".dwg" else f"Type de fichier non pris en charge: {ext or mime}"
            db.commit()
            return {"file_id": file_rec.id, "status": "unsupported", "error": file_rec.processing_error}

        file_rec.page_count = 1
        file_rec.processing_status = "completed"
        db.add(ExtractedPage(file_id=file_rec.id, page_number=1, text=text,
                             classification="plan" if ext in cad.CAD_EXT else classify_page(text)))
        for chunk in chunk_text(text):
            db.add(DocumentChunk(file_id=file_rec.id, page_number=1, text=chunk))
        db.commit()
        return {"file_id": file_rec.id, "status": "completed", "chars": len(text)}
    except Exception as exc:
        file_rec.processing_status = "failed"
        file_rec.processing_error = str(exc)
        db.commit()
        return {"file_id": file_rec.id, "status": "failed", "error": str(exc)}
