"""Fichiers créés par l'IA à la demande du patron : un PDF (lettre, rapport, compte rendu, attestation…) ou un tableur Excel.

Le contenu vient du patron ou de l'IA ; ce module ne fait que le mettre en forme, sans rien ajouter. Le fichier devient un
document de la conversation (téléchargeable, partageable) et peut être joint à un brouillon d'e-mail. Rien ne part tout seul.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Artifact, new_id
from app.services import company_dict, store_artifact

MAX_PDF_CHARS = 60_000
MAX_SHEETS, MAX_ROWS, MAX_COLS = 20, 5000, 60
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MakeFileError(ValueError):
    pass


def _filename(title: str, ext: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", title, flags=re.UNICODE).strip().replace(" ", "_")[:60] or "document"
    return f"{stem}.{ext}"


def _inline(text: str) -> str:
    """Texte sûr pour reportlab : échappé, **gras** et *italique* gardés."""
    t = escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", t)


def _out(kind: str, filename: str) -> Path:
    folder = settings.artifacts_path / "made"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{Path(filename).stem}_{new_id()[:8]}.{kind}"


def make_pdf(db: Session, title: str, content: str, user_id: str | None) -> Artifact:
    """PDF A4 : en-tête de l'entreprise, titre, date, texte (titres « # », listes « - », **gras**), pages numérotées."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    title, content = (title or "").strip(), (content or "").strip()
    if not title or not content:
        raise MakeFileError("Il faut un titre et un contenu.")
    if len(content) > MAX_PDF_CHARS:
        raise MakeFileError(f"Contenu trop long ({len(content)} caractères, {MAX_PDF_CHARS} au plus).")
    company = company_dict(db)
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=10.5, leading=15, spaceAfter=6)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=17, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    story: list = [Paragraph(_inline(title), h1), Paragraph(datetime.now().strftime("%d/%m/%Y"), small), Spacer(1, 6 * mm)]
    bullets: list = []

    def flush() -> None:
        if bullets:
            story.append(ListFlowable([ListItem(Paragraph(b, body), leftIndent=10) for b in bullets], bulletType="bullet", start="•"))
            bullets.clear()

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if re.match(r"^[-*•]\s+", line):
            bullets.append(_inline(re.sub(r"^[-*•]\s+", "", line)))
            continue
        flush()
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        story.append(Paragraph(_inline(m.group(2)), h2) if m else Paragraph(_inline(line), body))
    flush()

    head = " · ".join(x for x in (company.get("name"), company.get("phone"), company.get("email")) if x)

    def decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, A4[1] - 12 * mm, head[:110])
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    name = _filename(title, "pdf")
    dest = _out("pdf", name)
    SimpleDocTemplate(str(dest), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=16 * mm,
                      title=title, author=company.get("name") or "").build(story, onFirstPage=decorate, onLaterPages=decorate)
    art = store_artifact(db, dest, name, "made_file", dest.stem, f"made-{dest.stem}", user_id)
    db.commit()
    return art


def _cell(v):
    if isinstance(v, (int, float)) or v is None:
        return v
    s = str(v)
    return s[:32000]


def make_spreadsheet(db: Session, title: str, sheets: list, user_id: str | None) -> Artifact:
    """Classeur Excel : une feuille par entrée {name, rows} ; la 1re ligne est l'en-tête (gras, figée) ; « =… » reste une formule."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    title = (title or "").strip()
    if not title:
        raise MakeFileError("Il faut un titre.")
    if not isinstance(sheets, list) or not sheets:
        raise MakeFileError("Il faut au moins une feuille avec des lignes.")
    if len(sheets) > MAX_SHEETS:
        raise MakeFileError(f"Trop de feuilles ({MAX_SHEETS} au plus).")
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for i, sh in enumerate(sheets, start=1):
        if not isinstance(sh, dict) or not isinstance(sh.get("rows"), list) or not sh["rows"]:
            raise MakeFileError(f"Feuille {i} : il faut une liste de lignes.")
        rows = sh["rows"]
        if len(rows) > MAX_ROWS or any(not isinstance(r, list) or len(r) > MAX_COLS for r in rows):
            raise MakeFileError(f"Feuille {i} : {MAX_ROWS} lignes et {MAX_COLS} colonnes au plus, chaque ligne étant une liste.")
        name = re.sub(r"[\[\]:*?/\\]", " ", str(sh.get("name") or f"Feuille {i}")).strip()[:31] or f"Feuille {i}"
        while name in used:
            name = f"{name[:28]} {i}"
        used.add(name)
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append([_cell(v) for v in r])
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for col in range(1, max(len(r) for r in rows) + 1):
            width = max((len(str(r[col - 1])) for r in rows if len(r) >= col and r[col - 1] is not None), default=8)
            ws.column_dimensions[get_column_letter(col)].width = min(max(width + 2, 8), 60)
    name = _filename(title, "xlsx")
    dest = _out("xlsx", name)
    wb.save(str(dest))
    art = store_artifact(db, dest, name, "made_file", dest.stem, f"made-{dest.stem}", user_id, mime=XLSX_MIME)
    db.commit()
    return art
