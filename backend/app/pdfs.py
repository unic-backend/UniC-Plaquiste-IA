"""Génération de PDF réels (ReportLab). Jamais de faux liens."""

from __future__ import annotations

import re

from contextvars import ContextVar
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
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
    whole = (currency or "").upper().replace(" ", "") in ("FCFA", "XOF", "CFA") and float(value).is_integer()
    return f"{fr_num(value, 0 if whole else 2)}{cur}"   # FCFA : pas de centimes quand le montant est rond


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
TINT = colors.HexColor("#F3F5FA")          # fonds des encadrés (client, objet, références)
LINE = colors.HexColor("#DDE2EC")          # filets fins entre les lignes du tableau
YELLOW_DARK = colors.HexColor("#B98C00")   # or lisible sur blanc (accroche)
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
    """Titre de section : texte bleu, filet or dessous (plus de bandeau plein : lecture plus claire)."""
    t = Table([[Paragraph(text, _st("bar", fontSize=10.5, textColor=BLUE, leading=13))]], colWidths=[width_mm * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, YELLOW), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), P(3))]))
    return t


def _fit_title(text: str, max_mm: float = 46) -> int:
    for size in range(24, 10, -1):
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


def _sum_lines(lines: list[list[str]], currency: str = "") -> str:
    total = sum(_amount(l[-1]) for l in lines)
    return f"{round(total):,}".replace(",", " ") + (f" {currency}" if currency else "")


# --- Lignes lisibles : désignation propre, unité dans sa colonne ---------------

UNIT_FR = {"u": "Unité", "unité": "Unité", "unite": "Unité", "pce": "Pièce", "pièce": "Pièce", "piece": "Pièce", "barre": "Barre",
           "paquet": "Paquet", "sac": "Sac", "seau": "Seau", "rouleau": "Rouleau", "forfait": "Forfait", "m2": "m²", "m²": "m²",
           "ml": "ml", "m": "m", "kg": "kg", "l": "L", "boîte": "Boîte", "boite": "Boîte", "carton": "Carton", "lot": "Lot",
           "jour": "Jour", "h": "Heure", "heure": "Heure", "plaque": "Plaque"}
_CONTAINER = {"paquets": "paquet", "sacs": "sac", "seaux": "seau", "rouleaux": "rouleau", "cartons": "carton", "barres": "barre", "lots": "lot"}
_PACK_RE = re.compile(r"\(\s*(paquet|sac|seau|rouleau|carton|boîte|boite|lot)s?\s+de\s+(\d+)[^)]*\)", re.I)
_PRICE_PAREN_RE = re.compile(r"\([^)]*\d[\d\s.,]*\s*(?:fcfa|f\s?cfa|cfa|xof|€|eur)\b[^)]*\)", re.I)
_LEAD_RE = re.compile(r"^(paquets?|sacs?|seaux?|rouleaux?|cartons?|barres?|lots?)\s+(?:de\s+|d['’]\s*)?(.+)$", re.I)


def _singular(word: str) -> str:
    """Premier mot d'une désignation au singulier (une ligne = un article) : « Tiges » → « Tige » ; « Vis », « Frais » restent."""
    if len(word) > 3 and word[-1] in "sS" and word[-2:].lower() not in ("ss", "us", "is", "os", "as"):
        return word[:-1]
    return word


def tidy_item(designation: str, unit: str) -> tuple[str, str]:
    """Ligne de devis écrite comme un professionnel : le conditionnement et le prix sortent de la désignation.
    « Tiges 1 m (paquet de 100 tiges à 300 FCFA) » + paquet → (« Tige 1 m », « Paquet de 100 ») ;
    « Paquet vis 25 mm » → (« Vis 25 mm », « Paquet ») ; « Barre de fourrure (2,80 m) » + barre → (« Fourrure 2,80 m », « Barre »)."""
    d, u = " ".join(_strip(designation).split()), _strip(unit).lower()
    if _is_labour(d) or "à la charge" in d.lower():   # main-d'œuvre, livraison : le libellé du patron reste tel quel
        return d, UNIT_FR.get(u, unit or "")
    pack = None
    m = _PACK_RE.search(d)
    if m:
        pack, d = (m.group(1).lower(), m.group(2)), d[:m.start()] + d[m.end():]
    d = _PRICE_PAREN_RE.sub("", d)   # un prix n'a rien à faire dans la désignation : il est dans sa colonne
    m = _LEAD_RE.match(d.strip())
    if m:
        cont = _CONTAINER.get(m.group(1).lower(), m.group(1).lower())
        if not u or u in GENERIC_UNITS or u == cont:
            d, u = m.group(2), cont
    d = re.sub(r"\(\s*([\d.,]+\s*(?:mm|cm|m|kg|l|ml)\b[^)]*)\)", r"\1", d)   # « (2,80 m) » → « 2,80 m »
    d = " ".join(re.sub(r"\(\s*\)", "", d).split()).strip(" -–—:;,")
    if d:
        first, _, rest = d.partition(" ")
        d = (_singular(first[:1].upper() + first[1:]) + (" " + rest if rest else ""))
    if pack and (not u or u in GENERIC_UNITS or u == pack[0]):
        label = f"{pack[0].capitalize()} de {pack[1]}"
    else:
        label = UNIT_FR.get(u, unit or "Unité")
    return d or _strip(designation), label


# --- Montant en lettres (« Arrêté le présent devis à la somme de … ») ---------

_UNITS = ("zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize "
          "dix-sept dix-huit dix-neuf").split()
_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _below_100(n: int, final: bool = True) -> str:
    if n < 20:
        return _UNITS[n]
    t, u = divmod(n, 10)
    if t == 7:
        return "soixante et onze" if u == 1 else "soixante-" + _UNITS[10 + u]
    if t == 8:
        return ("quatre-vingts" if final else "quatre-vingt") if u == 0 else "quatre-vingt-" + _UNITS[u]
    if t == 9:
        return "quatre-vingt-" + _UNITS[10 + u]
    return _TENS[t] + ("" if u == 0 else " et un" if u == 1 else "-" + _UNITS[u])


def _below_1000(n: int, final: bool = True) -> str:
    """`final` : rien ne suit (pas « mille ») — « deux cents », mais « deux cent mille » ; « quatre-vingts », mais « quatre-vingt mille »."""
    c, r = divmod(n, 100)
    parts = []
    if c:
        parts.append("cent" if c == 1 else _UNITS[c] + " cent" + ("s" if r == 0 and final else ""))
    if r:
        parts.append(_below_100(r, final))
    return " ".join(parts)


def en_lettres(n: int) -> str:
    """Nombre entier en toutes lettres, orthographe traditionnelle : 2 791 000 → « deux millions sept cent quatre-vingt-onze mille »."""
    if n == 0:
        return "zéro"
    parts = []
    for value, name in ((10 ** 9, "milliard"), (10 ** 6, "million")):
        q, n = divmod(n, value)
        if q:
            parts.append(f"{en_lettres(q) if q >= 1000 else _below_1000(q)} {name}{'s' if q > 1 else ''}")
    q, n = divmod(n, 1000)
    if q:
        parts.append("mille" if q == 1 else _below_1000(q, final=False) + " mille")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


_CUR_RE = re.compile(r"\s*(FCFA|F CFA|XOF|EUR|€|\$)\s*$", re.I)


def _currency_of(cells: list[str]) -> str:
    """Devise commune à toutes les cellules de prix (affichée une fois dans l'en-tête de colonne) ; « » si elles diffèrent."""
    found = {(_CUR_RE.search(_strip(c)) or [None, ""])[1].upper() for c in cells if re.search(r"\d", _strip(c))}
    return found.pop() if len(found) == 1 else ""


def _labour_table(heads: list[str], lines: list[list[str]], currency: str = "") -> tuple[list[str], list[list[str]]]:
    """Tableau de la main-d'œuvre : N° | Désignation | Surface (m²) | Prix unitaire (par m²) | Montant."""
    qi, ui = heads.index("Qté"), heads.index("Unité")
    per_m2 = all(_strip(l[ui]) == "m²" or _strip(l[qi]).lower().endswith(("m²", "m2")) for l in lines)
    hd = ["N°", "Désignation", "Surface (m²)" if per_m2 else "Qté"] + [
        ("Prix unitaire (par m²)" if per_m2 and h.startswith("P.U") else h) for h in heads[4:]]
    out = []
    for n, l in enumerate(lines, 1):
        q = _strip(l[qi])
        if per_m2:
            q = re.sub(r"\s*m(²|2)$", "", q) + " m²"
        elif _strip(l[ui]):
            q = f"{q} {_strip(l[ui]).lower()}"
        out.append([str(n), l[1], q] + l[4:])
    return hd, out


def _columns(headers: list[str], rows: list[list[str]]):
    """Tableau professionnel : N° | Désignation | Unité | Qté | P.U. | Montant (la devise une seule fois, dans l'en-tête).
    Rend (en-têtes, lignes, prix présents, devise) ou None si le tableau n'a ni désignation ni quantité."""
    low = [h.lower() for h in headers]

    def find(*keys):
        for n, h in enumerate(low):
            if any(h.startswith(k) for k in keys):
                return n
        return None

    d, q, u = find("désignation", "designation"), find("qté", "quantité"), find("unité", "unite")
    pu, tot = find("p.u", "pu", "prix u"), find("total", "montant")
    if d is None or q is None:
        return None
    currency = _currency_of([r[i] for r in rows for i in (pu, tot) if i is not None])
    unit_cell = lambda s: _CUR_RE.sub("", _clean(s)) if currency else _clean(s)   # noqa: E731
    sfx = f" ({currency})" if currency else ""
    heads = ["N°", "Désignation", "Unité", "Qté"] + ([f"{_strip(headers[pu]) or 'P.U.'}{sfx}"] if pu is not None else []) + ([f"Montant{sfx}"] if tot is not None else [])
    out = []
    for n, r in enumerate(rows, 1):
        name, unit = tidy_item(r[d], r[u] if u is not None else "")
        line = [str(n), name, unit, _clean(_strip(r[q]))]
        free = "à la charge" in name.lower() and (tot is None or _amount(r[tot]) == 0)   # « Livraison : à la charge du client » : pas de « 0 »
        if pu is not None:
            line.append("—" if free else unit_cell(r[pu]))
        if tot is not None:
            line.append("—" if free else unit_cell(r[tot]))
        out.append(line)
    return heads, out, pu is not None, currency


def _meta_pairs(meta_lines: list[str]) -> list[tuple[str, str]]:
    """« Date 04/11/2026 » → (« Date », « 04/11/2026 ») ; le statut interne (brouillon…) n'apparaît jamais chez le client."""
    out = []
    for m in (x.strip() for x in meta_lines):
        if not m or m.lower().startswith("statut"):
            continue
        k, sep, v = m.partition(":") if ":" in m[:14] else m.partition(" ")
        out.append((k.strip(), v.strip()) if sep and v.strip() else ("", m))
    return out


def _arrete(doc_label: str) -> str:
    low = doc_label.lower()
    if low.startswith("facture") or low.startswith("situation"):
        return "Arrêtée la présente facture à la somme de"
    if low == "avoir":
        return "Arrêté le présent avoir à la somme de"
    if low == "devis":
        return "Arrêté le présent devis à la somme de"
    return ""


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
    qr_url: str = "",
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    e = _entreprise(company)
    is_quote = doc_label.upper() == "DEVIS"
    txt = _st("txt", fontName="Helvetica", fontSize=8.5, leading=11.5)
    small = _st("small", fontName="Helvetica", fontSize=7.8, leading=10.2, textColor=MUTED)
    bullet = _st("bullet", fontName="Helvetica", fontSize=7.8, leading=10.2, textColor=MUTED, leftIndent=9, bulletIndent=0)
    cell = _st("cell", fontName="Helvetica", fontSize=8.5, leading=11)
    cellc = _st("cellc", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_CENTER)
    cellr = _st("cellr", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_RIGHT)
    cellb = _st("cellbr", fontSize=8.5, leading=11, alignment=TA_RIGHT)
    headw = _st("headw", fontSize=7.8, leading=10, textColor=colors.white)
    label = _st("label", fontSize=7, leading=9, textColor=MUTED)

    # --- en-tête : logo + identité à gauche ; type, numéro et références à droite
    contact = " · ".join(x for x in (f"{e['gerant']}, gérant" if e["gerant"] else "", f"Tél. {e['telephone']}" if e["telephone"] else "") if x)
    legal = " · ".join(x for x in ((f"NINEA : {e['ninea']}" if e["ninea"] else ""), (f"RCCM : {e['rccm']}" if e["rccm"] else "")) if x)
    ident = [Paragraph(e["nom"], _st("nom", fontSize=17, textColor=BLUE, leading=20)),
             Paragraph(" · ".join(x for x in (e["accroche"], SOUS_ACCROCHE) if x), _st("accr", fontSize=9, textColor=YELLOW_DARK, leading=12)),
             Spacer(1, P(2))] + [Paragraph(x, small) for x in (e["specialite"], contact, " · ".join(x for x in (e["adresse"], e["site"]) if x), legal) if x]
    tsize = _fit_title(doc_label, 56)
    refs = Table([[Paragraph(k.upper(), label), Paragraph(v, _st("rv", fontSize=8.5, leading=11, alignment=TA_RIGHT))] for k, v in _meta_pairs(meta_lines)] or [[""]],
                 colWidths=[20 * mm, 38 * mm])
    refs.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                              ("TOPPADDING", (0, 0), (-1, -1), P(2.2)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(2.2)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
    titre = [Paragraph(doc_label.upper(), _st("titre", fontSize=tsize, textColor=BLUE, alignment=TA_RIGHT, leading=tsize + 3)), Spacer(1, P(3)), refs]
    if _logo_ok():
        head = Table([[RLImage(str(LOGO), width=P(26) * mm, height=P(26) * mm), ident, titre]], colWidths=[P(29) * mm, (122 - P(29)) * mm, 58 * mm])
    else:
        head = Table([[ident, titre]], colWidths=[122 * mm, 58 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    rule = Table([[""]], colWidths=[180 * mm], rowHeights=[1.6])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), YELLOW)]))
    story: list = [head, Spacer(1, P(4)), rule, Spacer(1, P(6))]

    # --- client et objet, côte à côte, sur fond teinté
    party_lines = [l for l in (party_right[1] or "").split("\n") if l.strip()]
    who = party_lines[0] if party_lines else ""
    client = [Paragraph(party_right[0].upper(), label), Spacer(1, P(1.5)),
              Paragraph(who or "—", _st("cn", fontSize=11, leading=14))] + [Paragraph(l, txt) for l in party_lines[1:]]
    obj_text = (title or doc_label) + (("<br/>" + notes.replace("\n", "<br/>")) if notes and not is_quote else "")
    objet = [Paragraph("OBJET", label), Spacer(1, P(1.5)), Paragraph(obj_text, _st("obj", fontName="Helvetica", fontSize=8.5, leading=11.5, alignment=TA_JUSTIFY))]
    cards = Table([[client, "", objet]], colWidths=[62 * mm, 4 * mm, 114 * mm])
    cards.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), TINT), ("BACKGROUND", (2, 0), (2, 0), TINT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), P(6)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(6)),
                               ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story += [cards, Spacer(1, P(8))]

    # --- tableaux
    mapped = _columns(headers, rows)
    split_labour = False
    currency = ""
    if mapped:
        heads, body, has_pu, currency = mapped
        mat_body, lab_body = body, []
        if is_quote:   # règle du patron : la main-d'œuvre n'est JAMAIS dans le tableau des matériaux ; elle a son propre tableau en dessous
            mat_body = [l for l in body if not _is_labour(_strip(l[1]))]
            lab_body = [l for l in body if _is_labour(_strip(l[1]))]
            if not mat_body:   # un devis de main-d'œuvre seule : un seul tableau, inchangé
                mat_body, lab_body = body, []
            for n, l in enumerate(mat_body, 1):
                l[0] = str(n)
        split_labour = bool(lab_body)

        def grid(hd: list[str], lines: list[list[str]], sub: tuple[str, str] | None) -> Table:
            ncol = len(hd)
            if hd[2] == "Unité":   # N° | Désignation | Unité | Qté | P.U. | Montant
                widths = [9, 0, 25, 16, 27, 31][:ncol]
            else:                  # main-d'œuvre : N° | Désignation | Surface | P.U. par m² | Montant
                widths = [9, 0, 25, 34, 31][:ncol]
            widths[1] = 180 - sum(widths)
            styles = [cellc, cell] + [cellc if (h == "Unité") else cellr for h in hd[2:]]
            data = [[Paragraph(h, _st(f"h{n}", fontSize=7.8, leading=10, textColor=colors.white,
                                         alignment=TA_LEFT if n == 1 else TA_CENTER if n in (0,) or h == "Unité" else TA_RIGHT)) for n, h in enumerate(hd)]]
            for line in lines:
                data.append([Paragraph(str(c), styles[n] if n < ncol - 1 else cellb) for n, c in enumerate(line)])
            has_sub = bool(sub)
            if has_sub:
                data.append([""] + [Paragraph(sub[0], _st("sl", fontSize=8.5, leading=11))] + [""] * (ncol - 3) + [Paragraph(sub[1], cellb)])
            t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
            st = [("BACKGROUND", (0, 0), (-1, 0), BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), P(3.6)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(3.6)),
                  ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                  ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE)]
            for r in range(1, len(data) - (1 if has_sub else 0)):
                if r % 2 == 0:
                    st.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
            if has_sub:
                st += [("BACKGROUND", (0, -1), (-1, -1), TINT), ("SPAN", (1, -1), (-2, -1)), ("LINEABOVE", (0, -1), (-1, -1), 0.8, BLUE)]
            t.setStyle(TableStyle(st))
            return t

        if split_labour:
            story += [_bar("Tableau des matériaux (fournitures)"), Spacer(1, P(3)),
                      grid(heads, mat_body, ("Sous-total matériaux HT", _sum_lines(mat_body, currency))), Spacer(1, P(8))]
            lab_heads, lab_rows = _labour_table(heads, lab_body, currency)
            story += [_bar("Main-d'œuvre (pose)"), Spacer(1, P(3)),
                      grid(lab_heads, lab_rows, ("Sous-total main-d'œuvre HT", _sum_lines(lab_body, currency))), Spacer(1, P(8))]
        else:
            story += [_bar("Tableau des matériaux (fournitures)" if is_quote else "Détail"), Spacer(1, P(3)),
                      grid(heads, mat_body, None), Spacer(1, P(8))]
    else:
        story += [_bar("Détail"), Spacer(1, P(3))]
        data = [[Paragraph(h, headw) for h in headers]] + [[Paragraph(str(c), cell) for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm * 180 / sum(col_widths) for w in col_widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), P(3.6)),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), P(3.6)), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA])]))
        story += [t, Spacer(1, P(8))]

    # --- totaux : récapitulatif à droite (sans doublon), montant en lettres à gauche
    if totals:
        final = next(((a, b) for a, b in totals if a == "Total"), None)
        has_vat = any(a.upper().startswith("TVA") for a, _ in totals)
        middle = [(a, b) for a, b in totals if (a, b) != final and (has_vat or not final or _clean(b) != _clean(final[1]))]
        recap = [[Paragraph(a, _st("ml", fontName="Helvetica", fontSize=8.5, leading=11)), Paragraph(_clean(b), cellb)] for a, b in middle]
        if final:
            recap.append([Paragraph("TOTAL TTC" if has_vat else "MONTANT TOTAL", _st("t1", fontSize=10.5, textColor=BLUE, leading=13)),
                          Paragraph(_clean(final[1]), _st("t2", fontSize=12, textColor=BLUE, alignment=TA_RIGHT, leading=14))])
        rt = Table(recap, colWidths=[38 * mm, 40 * mm])
        rst = [("TOPPADDING", (0, 0), (-1, -1), P(3)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(3)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("LINEBELOW", (0, 0), (-1, -2), 0.35, LINE)]
        if final:
            rst += [("BACKGROUND", (0, -1), (-1, -1), YELLOW), ("TOPPADDING", (0, -1), (-1, -1), P(6)), ("BOTTOMPADDING", (0, -1), (-1, -1), P(6))]
        rt.setStyle(TableStyle(rst))
        words = ""
        amount = _amount(final[1]) if final else 0
        if final and _arrete(doc_label) and amount > 0 and amount.is_integer() and currency in ("FCFA", "F CFA", "XOF"):
            lettres = en_lettres(int(amount))
            words = f"{_arrete(doc_label)} : <b>{lettres[:1].upper() + lettres[1:]} francs CFA</b> ({_clean(final[1])})."
        left_col = Paragraph(words, _st("words", fontName="Helvetica", fontSize=8.3, leading=11.5)) if words else ""
        story += [Table([[left_col, rt]], colWidths=[100 * mm, 80 * mm],
                        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                          ("RIGHTPADDING", (0, 0), (0, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0)])), Spacer(1, P(10))]

    if warnings:
        for w in warnings:
            story.append(Paragraph("Attention : " + w, _st("w", textColor=colors.HexColor("#B42318"))))
        story.append(Spacer(1, P(8)))
    for p in extra_paragraphs or []:
        story += [Paragraph(p, txt), Spacer(1, P(5))]
    if qr_url.startswith("https://"):   # QR du lien de paiement (Wave) : le client le scanne avec son téléphone
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        w = QrCodeWidget(qr_url)
        x0, y0, x1, y1 = w.getBounds()
        side = P(70)
        d = Drawing(side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), 0, 0])
        d.add(w)
        story += [Table([[d, Paragraph("Scanne ce code avec ton téléphone pour payer par Wave.", txt)]], colWidths=[side + P(8), None],
                        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])), Spacer(1, P(6))]

    # --- conditions (à gauche) et exclusions (à droite), comme sur le devis de référence, en plus compact
    if is_quote:
        labour = split_labour or any("main-d" in _strip(r[1]).lower() or "pose" in _strip(r[1]).lower() for r in rows if len(r) > 1)
        important = [b.strip() for b in (company.get("payment_terms") or "").split("\n") if b.strip()]
        important += [
            "Les prix unitaires s'entendent à l'unité indiquée (barre, paquet, sac…) ; le montant de chaque ligne figure dans la colonne « Montant ».",
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
        if any(re.search(r"\bled\b", _strip(r[1]), re.I) for r in rows if len(r) > 1):   # ruban LED au devis (plafond à gorge, îlot…)
            excl = [("Luminaires (le ruban LED listé au tableau est compris)." if re.search(r"\bLED\b", x) else x) for x in excl]
        cond = [Paragraph("Conditions", _st("ch", fontSize=9.5, textColor=BLUE, leading=12)), Spacer(1, P(2))] + \
               [Paragraph(b, bullet, bulletText="•") for b in important]
        exc = ([Paragraph("Ne sont pas inclus", _st("ex", fontSize=9.5, textColor=BLUE, leading=12)), Spacer(1, P(2))] +
               [Paragraph(x, bullet, bulletText="•") for x in excl]) if excl else ""
        story += [Table([[cond, exc]], colWidths=[108 * mm, 72 * mm],
                        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                          ("RIGHTPADDING", (0, 0), (0, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0)])), Spacer(1, P(12))]

    # --- signatures : un cadre par partie (signature à la main, ou champ de signature Adobe invisible dans le cadre)
    other = f"{party_right[0].capitalize()} ({who or party_right[0]})"
    box_w, box_h = 82 * mm, P(24) * mm
    shead = _st("sh", fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    mention = "Date et mention « Bon pour accord »" if is_quote else "Date : ____ / ____ / ________"
    sig = Table([[Paragraph(e["nom"], shead), Paragraph(other, shead)],
                 [Paragraph("Date : ____ / ____ / ________", small), Paragraph(mention, small)],
                 [SignBox(box_w, box_h, "Signature_UniC", owner_signature_path(), owner_stamp_path()), SignBox(box_w, box_h, "Signature_Client")]],
                colWidths=[90 * mm, 90 * mm])
    sig.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), P(2)), ("BOTTOMPADDING", (0, 0), (-1, -1), P(2)),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(KeepTogether(sig))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=P(10) * mm,
                            bottomMargin=P(14) * mm, title=f"{doc_label} {number}", author=e["nom"])
    foot = _footer(" · ".join(x for x in (e["nom"], legal) if x), doc_label, number)
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
