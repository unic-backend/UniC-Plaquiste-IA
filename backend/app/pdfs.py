"""Génération de PDF réels (ReportLab). Jamais de faux liens."""

from __future__ import annotations

import re

from contextvars import ContextVar
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Flowable
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
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


# --- Charte UniC Plaquiste (reprise du devis de référence du patron) ----------

BRAND_DIR = Path(__file__).parent / "brand"
LOGO = BRAND_DIR / "logo.png"
BLUE = colors.HexColor("#1A3FA0")
YELLOW = colors.HexColor("#F2C200")
GRID = colors.HexColor("#CCCCCC")
ZEBRA = colors.HexColor("#F4F6FB")
STATUS_FR = {"draft": "Brouillon", "approved": "Approuvé", "sent": "Envoyé", "paid": "Payé", "cancelled": "Annulé"}
MENTION_PU = "Les prix indiqués dans la colonne « Prix Unitaire » sont des prix à l'unité, et non des montants totaux. Le montant total de chaque ligne figure dans la colonne « Prix Total »."
GENERIC_UNITS = {"", "u", "unité", "unite"}


def _logo_ok() -> bool:
    """Logo présent ET lisible : un fichier corrompu ne doit jamais empêcher un document."""
    try:
        from PIL import Image
        with Image.open(LOGO) as im:
            im.verify()
        return True
    except Exception:
        return False


def _entreprise(company: dict) -> dict:
    """Identité du document : charte du patron, surchargée par les réglages société quand ils sont remplis."""
    try:
        from app import metier
        base = dict(metier.load().get("entreprise") or {})
    except Exception:   # la charte ne doit jamais empêcher un document
        base = {}
    out = {
        "nom": company.get("name") or base.get("nom") or "UniC Plaquiste",
        "accroche": base.get("accroche", ""), "specialite": base.get("specialite", ""),
        "gerant": base.get("gerant", ""), "telephone": company.get("phone") or base.get("telephone", ""),
        "adresse": base.get("adresse") or ", ".join(x for x in (company.get("city"), company.get("country")) if x),
        "site": company.get("website") or base.get("site", ""),
        "ninea": base.get("ninea", ""), "rccm": base.get("rccm", ""),
    }
    return out


_SCALE: ContextVar[float] = ContextVar("pdf_scale", default=1.0)


# Cadres de signature posés pendant le rendu : (page, x1, y1, x2, y2, nom du champ). Servent à créer les champs Adobe.
_SIGN_BOXES: ContextVar[list | None] = ContextVar("pdf_sign_boxes", default=None)


def owner_signature_path() -> Path:
    """Signature manuscrite du gérant (PNG transparent), posée dans le cadre UniC de chaque document."""
    from app.config import settings
    return settings.storage_path / "brand" / "signature.png"


STAMP_DEFAULT = BRAND_DIR / "stamp.png"   # cachet UniC Plaquiste intégré (demandé par le patron : déjà visible sur chaque document)


def uploaded_stamp_path() -> Path:
    from app.config import settings
    return settings.storage_path / "brand" / "stamp.png"


def owner_stamp_path() -> Path:
    """Cachet posé à côté de la signature : celui envoyé depuis l'appli s'il existe, sinon le cachet intégré."""
    up = uploaded_stamp_path()
    return up if up.exists() else STAMP_DEFAULT


class SignBox(Flowable):
    """Cadre de signature : bordure fine, libellé discret, signature du gérant éventuelle.
    Un champ de signature PDF invisible y est ajouté ensuite (Adobe : signer à la main ou placer sa signature)."""

    def __init__(self, width: float, height: float, field: str, image: Path | None = None, stamp: Path | None = None):
        super().__init__()
        self.width, self.height, self.field, self.image, self.stamp = width, height, field, image, stamp

    LABEL_H = 11   # le libellé est AU-DESSUS du cadre : le crayon du lecteur PDF (coin haut-gauche du champ) ne le cache plus

    def wrap(self, aw, ah):
        return self.width, self.height + self.LABEL_H

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(2, self.height + 3, "Signature et cachet")
        c.setStrokeColor(colors.HexColor("#1F3A93"))
        c.setLineWidth(0.8)
        c.roundRect(0, 0, self.width, self.height, 3, stroke=1, fill=0)
        from reportlab.lib.utils import ImageReader
        has_stamp = bool(self.stamp and self.stamp.exists())
        sig_w = self.width * (0.55 if has_stamp else 1.0)   # signature à gauche, cachet à droite
        if self.image and self.image.exists():
            try:
                img = ImageReader(str(self.image))
                iw, ih = img.getSize()
                k = min((sig_w - 12) * (0.9 if has_stamp else 0.6) / iw, (self.height - 8) * 0.85 / ih)
                w, h = iw * k, ih * k
                c.drawImage(img, (sig_w - w) / 2, (self.height - h) / 2, w, h, mask="auto")
            except Exception:
                pass
        if has_stamp:
            try:
                st = ImageReader(str(self.stamp))
                sw, sh = st.getSize()
                k = min((self.width - sig_w - 6) / sw, (self.height - 6) / sh)
                w, h = sw * k, sh * k
                c.saveState()
                c.setFillAlpha(0.92)
                c.drawImage(st, sig_w + (self.width - sig_w - w) / 2, (self.height - h) / 2, w, h, mask="auto")
                c.restoreState()
            except Exception:
                pass
        c.restoreState()
        boxes = _SIGN_BOXES.get()
        if boxes is not None:
            x, y = c.absolutePosition(0, 0)
            boxes.append((c.getPageNumber(), x, y, x + self.width, y + self.height, self.field))


def add_signature_fields(path: Path, boxes: list) -> None:
    """Champs de signature PDF (/Sig) invisibles posés sur les cadres : Acrobat propose « Signer » dans chaque cadre."""
    if not boxes:
        return
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

    writer = PdfWriter(clone_from=PdfReader(str(path)))
    fields = ArrayObject()
    for page_no, x1, y1, x2, y2, name in boxes:
        page = writer.pages[page_no - 1]
        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([FloatObject(round(v, 2)) for v in (x1, y1, x2, y2)]),
            NameObject("/F"): NumberObject(4), NameObject("/P"): page.indirect_reference,
        })
        ref = writer._add_object(widget)
        if "/Annots" not in page:
            page[NameObject("/Annots")] = ArrayObject()
        page["/Annots"].append(ref)
        fields.append(ref)
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): fields})
    with open(path, "wb") as fh:
        writer.write(fh)


def P(x: float) -> float:
    """Dimension mise à l'échelle : le document se resserre pour tenir sur une page."""
    return x * _SCALE.get()


def _st(name: str, **kw) -> ParagraphStyle:
    kw.setdefault("fontName", "Helvetica-Bold")
    size = kw.get("fontSize", 9)
    lead = kw.get("leading", size * 1.3)
    kw["fontSize"], kw["leading"] = P(size), P(lead)
    return ParagraphStyle(name, **kw)


def _footer(company_name: str, doc_label: str, number: str):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(A4[0] / 2, 6 * mm, f"{company_name} · {doc_label} {number} · page {doc.page}")
        canvas.restoreState()
    return _draw


def _bar(text: str, width_mm: float = 180) -> Table:
    t = Table([[Paragraph(text, _st("bar", fontSize=11, textColor=colors.white))]], colWidths=[width_mm * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _fit_title(text: str, max_mm: float = 46) -> int:
    for size in range(20, 10, -1):
        if stringWidth(text, "Helvetica-Bold", size) <= max_mm * mm:
            return size
    return 11


def _clean(v: str) -> str:
    """« 4 500,00 FCFA » -> « 4 500 FCFA » ; « 13,00 » -> « 13 » (les décimales utiles restent)."""
    import re
    return re.sub(r"(\d),00\b", r"\1", v or "")


def _strip(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").strip()


_LABOUR_RE = re.compile(r"main[\s\-]*d['’ ]?\s*(?:œ|oe)uvre|^\s*pose\b|\bpose complète\b|^\s*façon\b", re.I)


def _is_labour(designation: str) -> bool:
    return bool(_LABOUR_RE.search(designation or ""))


def _amount(cell: str) -> float:
    """« 346 500 FCFA » -> 346500.0 (0 si illisible)."""
    m = re.sub(r"[^\d,]", "", _strip(cell)).replace(",", ".")
    try:
        return float(m)
    except ValueError:
        return 0.0


def _sum_lines(lines: list[list[str]]) -> str:
    total = sum(_amount(l[-1]) for l in lines)
    cur = " FCFA" if any("FCFA" in _strip(l[-1]) for l in lines) else ""
    return f"{round(total):,}".replace(",", " ") + cur


def _labour_table(heads: list[str], lines: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Tableau de la main-d'œuvre : Désignation | Surface (m²) | Prix unitaire (par m²) | Prix Total."""
    qi = heads.index("Quantité")
    pi = heads.index("Prix Unitaire") if "Prix Unitaire" in heads else None
    ti = heads.index("Prix Total") if "Prix Total" in heads else None
    per_m2 = all(_strip(l[qi]).lower().endswith(("m²", "m2")) for l in lines)
    hd = ["Désignation", "Surface (m²)" if per_m2 else "Quantité"] + (["Prix unitaire (par m²)" if per_m2 else "Prix Unitaire"] if pi is not None else []) + (["Prix Total"] if ti is not None else [])
    out = []
    for l in lines:
        q = _strip(l[qi])
        if per_m2:
            q = re.sub(r"\s*m(²|2)$", "", q) + " m²"
        out.append([l[0], q] + ([l[pi]] if pi is not None else []) + ([l[ti]] if ti is not None else []))
    return hd, out


def _columns(headers: list[str], rows: list[list[str]]):
    """Tableau à la charte : Désignation | Prix Unitaire | Quantité | Prix Total (colonnes absentes omises)."""
    low = [h.lower() for h in headers]

    def find(*keys):
        for n, h in enumerate(low):
            if any(h.startswith(k) for k in keys):
                return n
        return None

    d, q, u = find("désignation", "designation"), find("qté", "quantité"), find("unité", "unite")
    pu, tot = find("p.u"), find("total")
    if d is None or q is None:
        return None
    heads = ["Désignation"] + (["Prix Unitaire"] if pu is not None else []) + ["Quantité"] + (["Prix Total"] if tot is not None else [])
    if pu is None and tot is None and u is not None:
        heads.append("Unité")
    out = []
    for r in rows:
        qty = _clean(r[q])
        unit = _strip(r[u]) if u is not None else ""
        if unit.lower() not in GENERIC_UNITS and (pu is not None or tot is not None):
            qty = f"{qty} {unit}"
        line = [r[d]] + ([_clean(r[pu])] if pu is not None else []) + [qty] + ([_clean(r[tot])] if tot is not None else [])
        if pu is None and tot is None and u is not None:
            line.append(unit)
        out.append(line)
    return heads, out, pu is not None


def _render(
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
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    e = _entreprise(company)
    is_quote = doc_label.upper() == "DEVIS"
    txt = _st("txt")
    cell = _st("cell", fontSize=8.5, leading=11)
    cellw = _st("cellw", fontSize=8.5, leading=11, textColor=colors.white)

    # --- en-tête : logo, identité, type et numéro du document
    infos = "<br/>".join(x for x in (
        e["specialite"], f"{e['gerant']} - Gérant" if e["gerant"] else "", f"Tel : {e['telephone']}" if e["telephone"] else "",
        e["adresse"], e["site"],
        " | ".join(x for x in ((f"NINEA : {e['ninea']}" if e["ninea"] else ""), (f"RCCM : {e['rccm']}" if e["rccm"] else "")) if x)) if x)
    ident = [Paragraph(e["nom"], _st("nom", fontSize=17, textColor=BLUE, leading=20)),
             Paragraph(e["accroche"], _st("accr", fontSize=10, textColor=YELLOW, leading=12)),
             Paragraph(SOUS_ACCROCHE, _st("accr2", fontSize=10, textColor=YELLOW, leading=12)),
             Paragraph(infos, _st("info", fontSize=8.5, leading=10.5))]
    tsize = _fit_title(doc_label)
    titre = [Paragraph(doc_label, _st("titre", fontSize=tsize, textColor=BLUE, alignment=TA_RIGHT, leading=tsize + 2)),
             Paragraph(f"N° {number}", _st("num", fontSize=10, alignment=TA_RIGHT, leading=14))]
    if _logo_ok():
        head = Table([[RLImage(str(LOGO), width=P(30) * mm, height=P(30) * mm), ident, titre]], colWidths=[P(33) * mm, (129 - P(33)) * mm, 51 * mm])
    else:
        head = Table([[ident, titre]], colWidths=[129 * mm, 51 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), P(0)),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), P(0))]))
    rule = Table([[""]], colWidths=[180 * mm], rowHeights=[2])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), YELLOW)]))
    story: list = [head, Spacer(1, P(3)), rule, Spacer(1, P(6))]

    # --- destinataire + références
    party_lines = [l for l in (party_right[1] or "").split("\n") if l.strip()]
    left = [Paragraph(party_right[0].upper(), _st("cl", fontSize=10, textColor=BLUE, leading=13))] + \
           [Paragraph(l, txt) for l in party_lines]
    metas = []
    for m in meta_lines:
        m = m.strip()
        if m.lower().startswith("statut "):
            continue   # le statut interne (brouillon…) n'a rien à faire sur un document client
        elif m.lower().startswith("date ") and ":" not in m[:6]:
            m = "Date : " + m[5:]
        elif m.lower().startswith("validité ") and ":" not in m[:10]:
            m = "Validité : " + m[9:]
        metas.append(Paragraph(m, txt))
    bloc = Table([[left, metas]], colWidths=[90 * mm, 90 * mm])
    bloc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [bloc, Spacer(1, P(6))]

    # --- objet
    low = doc_label.lower()
    objet = "Objet de la facture" if low.startswith("facture") or low.startswith("situation") else \
            "Objet de l'avoir" if low == "avoir" else f"Objet du {low}"
    story += [_bar(objet), Spacer(1, P(4)),
              Paragraph((title or doc_label) + (("<br/>" + notes.replace("\n", "<br/>")) if notes and not is_quote else ""),
                        _st("just", leading=12.5, alignment=TA_JUSTIFY)), Spacer(1, P(8))]

    # --- tableau
    mapped = _columns(headers, rows)
    split_labour = False
    if mapped:
        heads, body, has_pu = mapped
        if has_pu:
            story += [Paragraph("Important — Prix unitaires :", _st("imp", textColor=BLUE, leading=12)),
                      Paragraph(MENTION_PU, txt), Spacer(1, P(8))]
        mat_body, lab_body = body, []
        if is_quote:   # règle du patron : la main-d'œuvre n'est JAMAIS dans le tableau des matériaux ; elle a son propre tableau en dessous
            mat_body = [l for l in body if not _is_labour(_strip(l[0]))]
            lab_body = [l for l in body if _is_labour(_strip(l[0]))]
            if not mat_body:   # un devis de main-d'œuvre seule : un seul tableau, inchangé
                mat_body, lab_body = body, []
        split_labour = bool(lab_body)
        cellr = _st("cellr", fontSize=8.5, leading=11, alignment=TA_RIGHT)
        cellwr = _st("cellwr", fontSize=8.5, leading=11, textColor=colors.white, alignment=TA_RIGHT)

        def grid(hd: list[str], lines: list[list[str]], sub: tuple[str, str] | None) -> Table:
            ncol = len(hd)
            widths = {4: [78, 34, 28, 40], 3: [118, 34, 28] if "Prix Unitaire" in hd else [98, 40, 42], 2: [140, 40]}.get(ncol, [180 / ncol] * ncol)
            if hd[0] == "Désignation" and "Surface (m²)" in hd:
                widths = {4: [66, 30, 44, 40], 3: [98, 40, 42]}.get(ncol, widths)
            data = [[Paragraph(h, cellw if n == 0 else cellwr) for n, h in enumerate(hd)]]
            for line in lines:
                data.append([Paragraph(str(c), cell if n == 0 else cellr) for n, c in enumerate(line)])
            has_sub = bool(sub) and hd[-1] == "Prix Total"
            if has_sub:
                data.append([Paragraph(sub[0], cellw)] + [""] * (ncol - 2) + [Paragraph(_clean(sub[1]), cellwr)])
            t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
            st = [("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                  ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), P(3)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(3))]
            if has_sub:
                st += [("BACKGROUND", (0, -1), (-1, -1), BLUE), ("SPAN", (0, -1), (-2, -1))]
            for r in range(1, len(data) - (1 if has_sub else 0)):
                if r % 2 == 0:
                    st.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
            t.setStyle(TableStyle(st))
            return t

        first_total = totals[0] if totals else None
        if split_labour:
            story += [_bar("Tableau des matériaux (fournitures)"), Spacer(1, P(3)),
                      grid(heads, mat_body, ("Sous-total matériaux HT", _sum_lines(mat_body))), Spacer(1, P(8))]
            lab_heads, lab_rows = _labour_table(heads, lab_body)
            story += [_bar("Main-d'œuvre (pose)"), Spacer(1, P(3)),
                      grid(lab_heads, lab_rows, ("Sous-total main-d'œuvre HT", _sum_lines(lab_body))), Spacer(1, P(8))]
        else:
            story += [_bar("Tableau des matériaux (fournitures)" if is_quote else "Détail"), Spacer(1, P(3)),
                      grid(heads, mat_body, first_total), Spacer(1, P(8))]
    else:
        story += [_bar("Détail"), Spacer(1, P(3))]
        data = [[Paragraph(h, cellw) for h in headers]] + [[Paragraph(str(c), cell) for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm * 180 / sum(col_widths) for w in col_widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), P(3)),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), P(3)), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA])]))
        story += [t, Spacer(1, P(8))]

    # --- totaux : lignes intermédiaires, puis bandeau jaune sur le total
    if totals:
        labels = [a for a, _ in totals]
        final = next(((a, b) for a, b in totals if a == "Total"), None)
        middle = [(a, b) for a, b in totals[1:] if (a, b) != final] if mapped and mapped[0][-1] == "Prix Total" and not split_labour else \
                 [(a, b) for a, b in totals if (a, b) != final]
        if middle:
            mt = Table([[Paragraph(a, _st("ml", alignment=TA_RIGHT)), Paragraph(_clean(b), _st("mv", alignment=TA_RIGHT))] for a, b in middle],
                       colWidths=[130 * mm, 50 * mm])
            mt.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), P(2)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(2))]))
            story += [mt, Spacer(1, P(4))]
        if final:
            has_vat = any(l.upper().startswith("TVA") for l in labels)
            lab = "MONTANT TOTAL TTC" if has_vat else "MONTANT TOTAL"
            ttc = Table([[Paragraph(lab, _st("t1", fontSize=12, textColor=BLUE)),
                          Paragraph(_clean(final[1]), _st("t2", fontSize=12, textColor=BLUE, alignment=TA_RIGHT))]],
                        colWidths=[110 * mm, 70 * mm])
            ttc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), YELLOW), ("TOPPADDING", (0, 0), (-1, -1), P(6)),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), P(6)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            story += [ttc, Spacer(1, P(10))]

    if warnings:
        for w in warnings:
            story.append(Paragraph("Attention : " + w, _st("w", textColor=colors.HexColor("#B42318"))))
        story.append(Spacer(1, P(8)))
    for p in extra_paragraphs or []:
        story += [Paragraph(p, txt), Spacer(1, P(5))]

    # --- conditions et exclusions (devis), comme sur le devis de référence
    if is_quote:
        labour = split_labour or any("main-d" in _strip(r[1]).lower() or "pose" in _strip(r[1]).lower() for r in rows if len(r) > 1)
        important = [b.strip() for b in (company.get("payment_terms") or "").split("\n") if b.strip()]
        important += [
            "Les prix indiqués dans la colonne « Prix Unitaire » sont des prix à l'unité, et non des montants totaux.",
            *([] if labour else ["Ce devis porte uniquement sur les fournitures et matériaux. La main-d'œuvre fait l'objet d'un devis distinct."]),
            "UniC Plaquiste se charge de la commande, de la réception et de la vérification qualitative des matériaux.",
            "Les quantités pourront être ajustées selon la surface réelle constatée sur site.",
        ]
        try:
            from app import metier
            excl = list(metier.load().get("exclusions_habituelles") or [])
        except Exception:
            excl = []
        if not labour:
            excl.insert(0, "La main-d'œuvre et l'exécution des travaux.")
        story += [Paragraph("Conditions et modalités", _st("ch", fontSize=12, textColor=BLUE, leading=15)), Spacer(1, P(2)),
                  Paragraph("Conditions importantes :", _st("ci", textColor=BLUE, leading=12))]
        story += [Paragraph(f"• {b}", txt) for b in important]
        if excl:
            story += [Spacer(1, P(4)), Paragraph("Ne sont pas inclus :", _st("ex", textColor=BLUE, leading=12))]
            story += [Paragraph(f"• {x}", txt) for x in excl]
        story.append(Spacer(1, P(14)))

    # --- signatures : un cadre par partie (signature à la main, ou champ de signature Adobe invisible dans le cadre)
    who = party_lines[0] if party_lines else party_right[0]
    other = f"{party_right[0].capitalize()} ({who})"
    box_w, box_h = 82 * mm, P(26) * mm
    head = _st("sh", fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    sig = Table([[Paragraph(e["nom"], head), Paragraph(other, head)],
                 [Paragraph("Date : ____ / ____ / ________", txt), Paragraph("Date : ____ / ____ / ________", txt)],
                 [SignBox(box_w, box_h, "Signature_UniC", owner_signature_path(), owner_stamp_path()), SignBox(box_w, box_h, "Signature_Client")]],
                colWidths=[90 * mm, 90 * mm])
    sig.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), P(3)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(2)),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(KeepTogether(sig))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=P(9) * mm,
                            bottomMargin=P(14) * mm, title=f"{doc_label} {number}", author=e["nom"])
    foot = _footer(e["nom"], doc_label, number)
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return doc.page


SOUS_ACCROCHE = "Fourniture et pose"
MIN_SCALE = 0.72   # en dessous, le texte devient illisible : le document passe sur plusieurs pages (exception)


def build_document_pdf(path: Path, **kw) -> Path:
    """Un document tient sur UNE page : on resserre par paliers ; au-delà du minimum lisible, il s'étale (exception)."""
    scale = 1.0
    boxes: list = []
    while True:
        token, btoken = _SCALE.set(scale), _SIGN_BOXES.set(boxes)
        boxes.clear()
        try:
            pages = _render(path, **kw)
        finally:
            _SCALE.reset(token)
            _SIGN_BOXES.reset(btoken)
        if pages <= 1 or scale <= MIN_SCALE + 1e-9:
            break
        scale = round(max(MIN_SCALE, scale - 0.04), 2)
    if pages > 1:   # trop long même resserré : rendu lisible sur plusieurs pages
        token, btoken = _SCALE.set(0.9), _SIGN_BOXES.set(boxes)
        boxes.clear()
        try:
            _render(path, **kw)
        finally:
            _SCALE.reset(token)
            _SIGN_BOXES.reset(btoken)
    try:
        add_signature_fields(path, boxes)
    except Exception:   # le document reste valable sans champ Adobe (cadres dessinés quand même)
        import logging
        logging.getLogger("unic.pdfs").exception("Champs de signature non ajoutés")
    return path


def validate_pdf(path: Path) -> bool:
    data = path.read_bytes()[:8]
    return data.startswith(b"%PDF") and path.stat().st_size > 200
