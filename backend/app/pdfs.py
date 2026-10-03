"""Génération de PDF réels (ReportLab). Jamais de faux liens."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
)

INK = colors.HexColor("#1A1814")
COPPER = colors.HexColor("#B8612E")
PAPER = colors.HexColor("#FBF8F3")
RULE = colors.HexColor("#D9D0C4")
MUTED = colors.HexColor("#6B645B")
GREEN = colors.HexColor("#2C4A3E")
WARN = colors.HexColor("#8A3B12")


def fr_num(value: float | None, nd: int = 2) -> str:
    if value is None:
        return "—"
    q = f"{value:,.{nd}f}"
    q = q.replace(",", " ").replace(".", ",")
    return q


def money(value: float | None, currency: str) -> str:
    if value is None:
        return "prix non renseigné"
    cur = f" {currency}" if currency else ""
    return f"{fr_num(value)}{cur}"


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "brand": ParagraphStyle(
            "brand", parent=base["Normal"], fontName="Times-Bold", fontSize=16,
            textColor=GREEN, leading=20, spaceAfter=0,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"], fontName="Helvetica", fontSize=8,
            textColor=MUTED, leading=11,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Normal"], fontName="Times-Bold", fontSize=18,
            textColor=INK, spaceBefore=6, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10,
            textColor=COPPER, spaceBefore=10, spaceAfter=4, tracking=0.4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica", fontSize=9,
            textColor=INK, leading=13,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica", fontSize=8,
            textColor=MUTED, leading=11,
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=8,
            textColor=WARN, leading=11,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName="Helvetica", fontSize=8,
            textColor=INK, leading=11,
        ),
        "cellb": ParagraphStyle(
            "cellb", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8,
            textColor=INK, leading=11,
        ),
        "right": ParagraphStyle(
            "right", parent=base["Normal"], fontName="Helvetica", fontSize=8,
            textColor=INK, alignment=TA_RIGHT,
        ),
        "foot": ParagraphStyle(
            "foot", parent=base["Normal"], fontName="Helvetica", fontSize=7,
            textColor=MUTED, alignment=TA_CENTER,
        ),
    }
    return styles


def _header_footer(company: dict, doc_label: str, number: str, status: str):
    styles = _styles()

    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(GREEN)
        canvas.rect(0, A4[1] - 8 * mm, A4[0], 8 * mm, fill=1, stroke=0)
        canvas.setFillColor(COPPER)
        canvas.rect(0, A4[1] - 10 * mm, A4[0], 2 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Times-Bold", 9)
        canvas.drawString(16 * mm, A4[1] - 6.2 * mm, "UNIC PLAQUISTE")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 16 * mm, A4[1] - 6.2 * mm, f"{doc_label}  {number}")

        canvas.setFillColor(RULE)
        canvas.rect(0, 0, A4[0], 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(
            A4[0] / 2,
            5 * mm,
            f"{company.get('name') or 'UniC Plaquiste'}  ·  page {doc.page}  ·  document généré par UniC AI  ·  {status.upper()}",
        )
        if status.lower() in ("draft", "brouillon"):
            canvas.setFillColor(colors.Color(0.72, 0.38, 0.18, alpha=0.12))
            canvas.saveState()
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.setFont("Times-Bold", 48)
            canvas.drawCentredString(0, 0, "BROUILLON")
            canvas.restoreState()
        canvas.restoreState()

    return _draw


def _company_block(company: dict, styles) -> list:
    bits = [Paragraph(f"<b>{company.get('name') or 'UniC Plaquiste'}</b>", styles["brand"])]
    lines = []
    for key in ("legal_name", "address", "city", "country", "phone", "email", "tax_id"):
        val = (company.get(key) or "").strip()
        if val:
            label = {"tax_id": "N° fiscal", "legal_name": "Raison", "phone": "Tél", "email": "E-mail"}.get(key)
            lines.append(f"{label + ' : ' if label and key in ('phone','email','tax_id') else ''}{val}")
    if not lines:
        lines.append("Coordonnées société non renseignées dans Paramètres — non inventées.")
    bits.append(Paragraph("<br/>".join(lines), styles["sub"]))
    return bits


def _party_table(left_title, left_body, right_title, right_body, styles):
    data = [
        [Paragraph(f"<b>{left_title}</b>", styles["h2"]),
         Paragraph(f"<b>{right_title}</b>", styles["h2"])],
        [Paragraph(left_body.replace("\n", "<br/>") or "—", styles["body"]),
         Paragraph(right_body.replace("\n", "<br/>") or "—", styles["body"])],
    ]
    t = Table(data, colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _items_table(headers, rows, col_widths, styles):
    head = [Paragraph(f"<b>{h}</b>", styles["cellb"]) for h in headers]
    data = [head]
    for row in rows:
        data.append([Paragraph(str(c), styles["cell"]) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ]))
    return t


def build_document_pdf(
    path: Path,
    *,
    company: dict,
    doc_label: str,
    number: str,
    title: str,
    status: str,
    meta_lines: list[str],
    party_left: tuple[str, str],
    party_right: tuple[str, str],
    headers: list[str],
    rows: list[list[str]],
    col_widths: list,
    totals: list[tuple[str, str]] | None = None,
    notes: str = "",
    warnings: list[str] | None = None,
    extra_paragraphs: list[str] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{doc_label} {number}",
        author=company.get("name") or "UniC Plaquiste",
    )
    story = []
    story.extend(_company_block(company, styles))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.6, color=COPPER, spaceAfter=8))
    story.append(Paragraph(title or doc_label, styles["h1"]))
    story.append(Paragraph(" · ".join(meta_lines), styles["small"]))
    story.append(Spacer(1, 8))
    story.append(_party_table(party_left[0], party_left[1], party_right[0], party_right[1], styles))
    story.append(Spacer(1, 10))
    story.append(_items_table(headers, rows, col_widths, styles))
    if totals:
        tot_data = [[Paragraph(a, styles["right"]), Paragraph(f"<b>{b}</b>", styles["right"])] for a, b in totals]
        tot = Table(tot_data, colWidths=[130 * mm, 50 * mm])
        tot.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (1, -1), (1, -1), 1, GREEN),
        ]))
        story.append(Spacer(1, 8))
        story.append(tot)
    if warnings:
        story.append(Spacer(1, 8))
        for w in warnings:
            story.append(Paragraph("⚠ " + w, styles["warn"]))
    if extra_paragraphs:
        for p in extra_paragraphs:
            story.append(Spacer(1, 6))
            story.append(Paragraph(p, styles["body"]))
    if notes:
        story.append(Paragraph("NOTES", styles["h2"]))
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["body"]))
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Document généré par UniC AI pour UniC Plaquiste. "
        "Les montants absents de la base UniC sont indiqués « prix non renseigné » "
        "et ne sont jamais inventés.",
        styles["small"],
    ))
    doc.build(story, onFirstPage=_header_footer(company, doc_label, number, status),
              onLaterPages=_header_footer(company, doc_label, number, status))
    return path


def validate_pdf(path: Path) -> bool:
    data = path.read_bytes()[:8]
    return data.startswith(b"%PDF") and path.stat().st_size > 200
