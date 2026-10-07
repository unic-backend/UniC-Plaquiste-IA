"""Export comptable des devis et factures : une ligne par ligne de document, lisible dans Excel.

- Totaux (HT, TVA, TTC, payé, reste) sur la PREMIÈRE ligne de chaque document seulement : une somme de colonne ne compte jamais deux fois.
- Valeur inconnue = cellule vide (jamais 0 inventé). Montants dans la devise du document.
- CSV : séparateur « ; », UTF-8 avec BOM, virgule décimale (ouverture directe dans Excel français).
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from openpyxl import Workbook
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Invoice, Quotation
from app.services import client_name_of

HEADERS = ["Type", "Numéro", "Date", "Client", "Statut", "Devise", "Ligne", "Description", "Quantité", "Unité",
           "Prix unitaire", "Total ligne", "Total HT", "Taux TVA %", "Montant TVA", "Total TTC", "Payé", "Reste à payer", "Échéance"]
MONEY = {10, 11, 12, 14, 15, 16, 17}   # colonnes (0-based) en montant


def _date(d: datetime | None) -> str:
    return d.date().isoformat() if d else ""


def _rate(r: float | None):
    return "" if r is None else round(r * 100, 3)


def rows(db: Session, kind: str, start: datetime | None = None, end: datetime | None = None) -> list[list]:
    """kind : « quotes » ou « invoices ». Filtre optionnel sur la date de création."""
    model = Quotation if kind == "quotes" else Invoice
    q = db.query(model).options(selectinload(model.items), joinedload(model.customer))
    if start:
        q = q.filter(model.created_at >= start)
    if end:
        q = q.filter(model.created_at <= end)
    out: list[list] = []
    for doc in q.order_by(model.created_at, model.number).all():
        is_inv = kind == "invoices"
        label = "Avoir" if is_inv and doc.kind == "credit" else ("Facture" if is_inv else "Devis")
        head = [label, doc.number, _date(doc.created_at), client_name_of(db, doc) or "", doc.status, doc.currency or ""]
        tot = [doc.subtotal, _rate(doc.vat_rate), doc.vat_amount, doc.total,
               doc.paid if is_inv else "", doc.remaining if is_inv else "", _date(doc.due_date) if is_inv else ""]
        items = sorted(doc.items, key=lambda x: x.position)
        for n, it in enumerate(items or [None]):
            line = ([n + 1, it.description, it.quantity, it.unit, it.unit_price, it.total] if it else ["", "", "", "", "", ""])
            t = tot if n == 0 else [""] * 7
            out.append(head + line + [("" if v is None else v) for v in t])
    return out


def to_csv(data: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(HEADERS)
    for r in data:
        w.writerow([str(v).replace(".", ",") if isinstance(v, float) else v for v in r])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def to_xlsx(data: list[list], sheet: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADERS)
    for r in data:
        ws.append(list(r))
    for col in MONEY:
        for cell in ws.iter_rows(min_row=2, min_col=col + 1, max_col=col + 1):
            cell[0].number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
