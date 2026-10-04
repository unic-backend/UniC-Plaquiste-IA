"""Corriger ou retirer un document déjà créé (devis, facture, bon de commande, bon de livraison).

Règle du patron : une correction MODIFIE le document fautif, elle n'en crée pas un second ; un document faux
et abandonné est RETIRÉ de la bibliothèque. Seuls les brouillons se touchent : un document approuvé est figé.
Tout est déterministe : les totaux sont recalculés ici, jamais par le modèle.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app import services as svc
from app.models import (Artifact, Customer, DeliveryNote, DeliveryNoteItem, Invoice, InvoiceItem, PurchaseOrder,
                        PurchaseOrderItem, Quotation, QuotationItem)

KINDS = {
    "quote": (Quotation, QuotationItem, "quotation_id", Quotation.number),
    "invoice": (Invoice, InvoiceItem, "invoice_id", Invoice.number),
    "po": (PurchaseOrder, PurchaseOrderItem, "order_id", PurchaseOrder.number),
    "dn": (DeliveryNote, DeliveryNoteItem, "note_id", DeliveryNote.number),
}
LABEL = {"quote": "devis", "invoice": "facture", "po": "bon de commande", "dn": "bon de livraison"}


class ReviseError(ValueError):
    pass


def find(db: Session, kind: str, number: str = "", last_id: str | None = None):
    if kind not in KINDS:
        raise ReviseError("Type de document inconnu.")
    model, _item, _fk, col = KINDS[kind]
    doc = None
    if number.strip():
        doc = db.query(model).filter(col == number.strip().upper()).first()
    elif last_id:
        doc = db.get(model, last_id)
    if doc is None:
        raise ReviseError(f"{LABEL[kind].capitalize()} introuvable : précise son numéro.")
    return doc


def _draft_only(kind: str, doc) -> None:
    if doc.status != "draft":
        raise ReviseError(f"Ce {LABEL[kind]} est « {doc.status} » : il est figé. Crée-en une nouvelle version au lieu de le modifier.")


def _match(items: list, ref) -> object:
    """Ligne désignée par son numéro (1, 2…) ou par un morceau de sa désignation. Ambiguïté = refus."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        pos = int(ref)
        hit = [i for i in items if i.position == pos]
    else:
        needle = str(ref).strip().lower()
        hit = [i for i in items if needle and needle in (i.description or "").lower()]
    if not hit:
        raise ReviseError(f"Ligne introuvable : « {ref} ».")
    if len(hit) > 1:
        raise ReviseError(f"« {ref} » désigne {len(hit)} lignes : précise le numéro de ligne.")
    return hit[0]


def _recompute(kind: str, doc, items: list) -> None:
    for pos, it in enumerate(sorted(items, key=lambda x: x.position), start=1):
        it.position = pos
        if kind != "dn":
            it.total = round(it.quantity * it.unit_price, 2) if it.unit_price is not None else None
    if kind == "dn":
        return
    priced = [i for i in items if i.total is not None]
    complete = bool(items) and len(priced) == len(items)
    subtotal = round(sum(i.total for i in priced), 2) if priced else None
    if kind == "po":
        doc.total = subtotal if complete else None
        return
    doc.subtotal = subtotal
    if subtotal is not None and doc.vat_rate is not None:
        doc.vat_amount = round(subtotal * doc.vat_rate, 2)
        doc.total = round(subtotal + doc.vat_amount, 2)
    else:
        doc.vat_amount = None
        doc.total = subtotal
    if kind == "quote":
        doc.prices_complete = complete
    else:
        doc.remaining = round((doc.total or 0) - (doc.paid or 0), 2) if doc.total is not None else None


def revise(db: Session, kind: str, doc, *, user_id: str | None, remove: list | None = None, add: list[dict] | None = None,
           update: list[dict] | None = None, title: str | None = None, vat_rate: float | None = None,
           client_name: str | None = None, objet: str | None = None) -> list[str]:
    """Applique les corrections au document lui-même, recalcule, régénère le PDF. Renvoie ce qui a changé."""
    _draft_only(kind, doc)
    _model, item_model, fk, _col = KINDS[kind]
    items = db.query(item_model).filter(getattr(item_model, fk) == doc.id).order_by(item_model.position).all()
    changes: list[str] = []
    for ref in remove or []:
        it = _match(items, ref)
        items.remove(it)
        db.delete(it)
        changes.append(f"ligne retirée : {it.description}")
    for u in update or []:
        it = _match(items, u.get("line"))
        if u.get("quantity") is not None:
            it.quantity = float(u["quantity"])
        if u.get("unit_price") is not None and kind != "dn":
            it.unit_price = float(u["unit_price"])
        if u.get("description"):
            it.description = u["description"]
        if u.get("unit"):
            it.unit = u["unit"]
        changes.append(f"ligne modifiée : {it.description}")
    for a in add or []:
        if not (a.get("description") or "").strip() or a.get("quantity") is None:
            raise ReviseError("Une ligne ajoutée exige une désignation et une quantité.")
        row = {"description": a["description"].strip(), "quantity": float(a["quantity"]), "unit": a.get("unit") or "u",
               "position": len(items) + 1, fk: doc.id}
        if kind != "dn":
            row["unit_price"] = float(a["unit_price"]) if a.get("unit_price") is not None else None
        it = item_model(**row)
        db.add(it)
        items.append(it)
        changes.append(f"ligne ajoutée : {it.description}")
    if title:
        doc.title = title
        changes.append("titre modifié")
    if objet and kind == "quote":
        doc.object_text = objet.strip()[:900]
        changes.append("objet du devis modifié")
    if vat_rate is not None and kind in ("quote", "invoice"):
        doc.vat_rate = vat_rate
        changes.append(f"TVA {round(vat_rate * 100, 2)} %")
    if client_name and kind in ("quote", "dn"):
        known = next((c for c in db.query(Customer).all() if (c.name or "").strip().lower() == client_name.strip().lower()), None)
        if known is not None:
            doc.customer_id = known.id
            if kind == "quote":
                doc.client_label = ""
        elif kind == "quote":
            doc.client_label = client_name.strip()
        changes.append(f"client : {client_name.strip()}")
    _recompute(kind, doc, items)
    doc.version = (doc.version or 1) + 1
    db.flush()
    db.expire(doc)
    {"quote": svc.generate_quote_pdf, "invoice": svc.generate_invoice_pdf, "po": svc.generate_po_pdf,
     "dn": svc.generate_dn_pdf}[kind](db, doc, user_id)
    svc.audit(db, user_id, f"revise_{kind}", kind, doc.id, "; ".join(changes)[:300])
    db.commit()
    db.refresh(doc)
    return changes


def discard(db: Session, kind: str, doc, user_id: str | None) -> str:
    """Retire un brouillon erroné de la bibliothèque (lignes, PDF, fiche). Jamais un document approuvé."""
    _draft_only(kind, doc)
    _model, item_model, fk, _col = KINDS[kind]
    if kind == "quote" and db.query(Invoice).filter(Invoice.quotation_id == doc.id).first():
        raise ReviseError("Une facture est liée à ce devis : retire-la d'abord.")
    number = doc.number
    db.query(item_model).filter(getattr(item_model, fk) == doc.id).delete()
    art = db.get(Artifact, doc.artifact_id) if doc.artifact_id else None
    if art is not None:
        try:
            os.remove(art.path)
        except OSError:
            pass
        db.delete(art)
    db.delete(doc)
    svc.audit(db, user_id, f"discard_{kind}", kind, number, "brouillon retiré")
    db.commit()
    return number
