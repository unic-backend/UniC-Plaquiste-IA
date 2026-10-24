"""Corriger ou retirer un document déjà créé (devis, facture, bon de commande, bon de livraison).

Règle du patron : une correction MODIFIE le document fautif, elle n'en crée pas un second ; un document faux
et abandonné est RETIRÉ de la bibliothèque (brouillons seulement). Un document approuvé, envoyé ou refusé SE MODIFIE aussi sur ordre du patron :
il repasse « à valider » (à ré-approuver), la modification est tracée dans le journal.
Exception légale : une FACTURE émise (approuvée, envoyée, payée) ne se réécrit jamais. Sa correction = un avoir qui l'annule
+ une nouvelle facture corrigée « à valider » (reissue) ; les versements déjà reçus passent sur la nouvelle facture.
Tout est déterministe : les totaux sont recalculés ici, jamais par le modèle.
"""
from __future__ import annotations

import math
import os
import re

from sqlalchemy.orm import Session

from app import pricecheck, services as svc
from app.models import (Artifact, Customer, DeliveryNote, DeliveryNoteItem, Invoice, InvoiceItem, PurchaseOrder,
                        PurchaseOrderItem, Quotation, QuotationItem)

KINDS = {
    "quote": (Quotation, QuotationItem, "quotation_id", Quotation.number),
    "invoice": (Invoice, InvoiceItem, "invoice_id", Invoice.number),
    "po": (PurchaseOrder, PurchaseOrderItem, "order_id", PurchaseOrder.number),
    "dn": (DeliveryNote, DeliveryNoteItem, "note_id", DeliveryNote.number),
}
GRID_KIND = {"quote": "selling", "invoice": "selling", "po": "purchase", "dn": "selling"}   # vente ; achat pour un bon de commande
LABEL = {"quote": "devis", "invoice": "facture", "po": "bon de commande", "dn": "bon de livraison"}


class ReviseError(ValueError):
    pass


def _number(value, what: str, line: str, *, positive: bool) -> float:
    """Quantité ou prix donné pour une ligne : un nombre fini, jamais négatif (ni nul pour une quantité)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ReviseError(f"{what} illisible pour « {line} » : {value!r}.")
    if not math.isfinite(v) or v < 0 or (positive and v == 0):
        hint = " (pour retirer la ligne, utilise remove)" if positive else ""
        raise ReviseError(f"{what} refusé pour « {line} » : {value!r}{hint}.")
    return v


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
           client_name: str | None = None, objet: str | None = None, lieu: str | None = None,
           new_number: str | None = None) -> list[str]:
    """Applique les corrections au document lui-même, recalcule, régénère le PDF. Renvoie ce qui a changé."""
    prev_status = doc.status
    if kind == "invoice" and prev_status != "draft":
        raise ReviseError(f"La facture {doc.number} est émise (« {prev_status} ») : elle ne se réécrit pas. "
                          "Sa correction passe par un avoir et une nouvelle facture (reissue).")
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
            it.quantity = _number(u["quantity"], "Quantité", it.description, positive=True)
        if u.get("unit_price") is not None and kind != "dn":
            it.unit_price = _number(u["unit_price"], "Prix unitaire", it.description, positive=False)
        if u.get("description"):
            it.description = u["description"]
        if u.get("unit"):
            it.unit = u["unit"]
        changes.append(f"ligne modifiée : {it.description}")
    for a in add or []:
        if not (a.get("description") or "").strip() or a.get("quantity") is None:
            raise ReviseError("Une ligne ajoutée exige une désignation et une quantité.")
        desc = a["description"].strip()
        row = {"description": desc, "quantity": _number(a["quantity"], "Quantité", desc, positive=True),
               "unit": a.get("unit") or "u", "position": len(items) + 1, fk: doc.id}
        if kind != "dn":
            price = _number(a["unit_price"], "Prix unitaire", desc, positive=False) if a.get("unit_price") is not None else None
            if price is None:   # pas de prix donné : celui de la grille du patron si l'article y figure, sinon « prix non renseigné »
                price = pricecheck.grid_price(db, desc, kind=GRID_KIND[kind])
            row["unit_price"] = price
        it = item_model(**row)
        db.add(it)
        items.append(it)
        changes.append(f"ligne ajoutée : {it.description}")
    if new_number and new_number.strip().upper() != doc.number:
        if kind != "quote":
            raise ReviseError("Seul le numéro d'un devis brouillon se change : les factures gardent leur suite.")
        n = new_number.strip().upper()
        if not svc.NUMBER_RE.match(n):
            raise ReviseError("Format attendu : UC-AAAA-BLOC-INITIALES, par exemple UC-2026-1008-MR.")
        if n in svc._taken_numbers(db, n):
            raise ReviseError(f"Le numéro {n} existe déjà.")
        if db.query(Invoice).filter(Invoice.quotation_id == doc.id).first():
            raise ReviseError("Une facture est liée à ce devis : son numéro ne change plus.")
        old_art = db.get(Artifact, doc.artifact_id) if doc.artifact_id else None
        if old_art is not None:   # le PDF porte l'ancien numéro : il est refait sous le nouveau
            try:
                os.remove(old_art.path)
            except OSError:
                pass
            doc.artifact_id = None
            db.delete(old_art)
        changes.append(f"numéro {doc.number} → {n}")
        doc.number = n
    if title:
        doc.title = title
        changes.append("titre modifié")
    if lieu and kind == "quote":
        doc.site_location = lieu.strip()[:255]
        changes.append("lieu du chantier modifié")
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
    if kind != "dn":
        for o in pricecheck.off_grid(db, items, GRID_KIND[kind]):
            changes.append((f"PRIX HORS GRILLE : « {o['ligne']} » à {o['trouve']:,.0f} (grille : {o['grille']:,.0f}) — "
                            "à confirmer par le patron").replace(",", " "))
    if prev_status != "draft":   # modifié sur ordre du patron : il n'y a plus d'approbation valable sur le nouveau contenu
        doc.status = "draft"
        if hasattr(doc, "approved_by"):
            doc.approved_by, doc.approved_at = None, None
        changes.append(f"statut « {prev_status} » → « à valider » : à ré-approuver par le patron")
    doc.version = (doc.version or 1) + 1
    db.flush()
    db.expire(doc)
    {"quote": svc.generate_quote_pdf, "invoice": svc.generate_invoice_pdf, "po": svc.generate_po_pdf,
     "dn": svc.generate_dn_pdf}[kind](db, doc, user_id)
    svc.audit(db, user_id, f"revise_{kind}", kind, doc.id, "; ".join(changes)[:300])
    db.commit()
    db.refresh(doc)
    return changes


def _copy(db: Session, src: Invoice, *, number: str, kind: str, title: str, notes: str, version: int) -> Invoice:
    new = Invoice(number=number, kind=kind, customer_id=src.customer_id, project_id=src.project_id, quotation_id=src.quotation_id,
                  title=title, status="draft", currency=src.currency, subtotal=src.subtotal, vat_rate=src.vat_rate,
                  vat_amount=src.vat_amount, total=src.total, paid=0, remaining=src.total, notes=notes, version=version,
                  corrects_id=src.id)
    db.add(new)
    db.flush()
    for it in db.query(InvoiceItem).filter(InvoiceItem.invoice_id == src.id).order_by(InvoiceItem.position).all():
        db.add(InvoiceItem(invoice_id=new.id, position=it.position, description=it.description, quantity=it.quantity,
                           unit=it.unit, unit_price=it.unit_price, total=it.total))
    return new


def reissue(db: Session, doc: Invoice, *, user_id: str | None, **corrections) -> tuple[Invoice, list[str]]:
    """Corrige une facture ÉMISE sans la réécrire : avoir du montant total qui l'annule, nouvelle facture corrigée « à valider »
    (numéro suivant, version suivante), versements reçus transférés. Rien n'est envoyé : le patron relit et approuve les deux."""
    if doc.kind == "credit":
        raise ReviseError(f"L'avoir {doc.number} est émis : il ne se corrige pas. Fais un nouvel avoir ou une nouvelle facture.")
    if doc.status == "draft":
        raise ReviseError("Une facture brouillon se corrige directement (revise).")
    if doc.status == "cancelled":
        raise ReviseError(f"La facture {doc.number} est déjà annulée : corrige la facture qui la remplace.")
    root = re.sub(r"-F\d*$", "", doc.number)
    credit = _copy(db, doc, number=svc.linked_number(db, "AV", quote_number=root), kind="credit",
                   title=f"Avoir sur la facture {doc.number}", notes=f"Annule la facture {doc.number}.", version=1)
    new = _copy(db, doc, number=svc.linked_number(db, "F", quote_number=root), kind=doc.kind, title=doc.title,
                notes=f"Remplace la facture {doc.number} (annulée par l'avoir {credit.number}).", version=doc.version or 1)
    moved = 0.0
    for p in list(doc.payments):   # l'argent reçu reste acquis : il règle la facture qui remplace
        p.invoice_id = new.id
        moved += p.amount or 0
    new.paid = svc.money_round(moved)
    prev = doc.status
    doc.status, doc.paid, doc.remaining = "cancelled", 0, 0
    doc.notes = ((doc.notes or "") + f"\nAnnulée par l'avoir {credit.number}, remplacée par la facture {new.number}.").strip()
    db.flush()
    db.expire(doc)
    svc.generate_invoice_pdf(db, doc, user_id)
    svc.generate_invoice_pdf(db, credit, user_id)
    svc.audit(db, user_id, "reissue_invoice", "invoice", doc.id, f"{doc.number} ({prev}) → avoir {credit.number} + facture {new.number}")
    db.flush()
    changes = [f"facture {doc.number} annulée par l'avoir {credit.number} (à valider)",
               f"nouvelle facture {new.number} à valider"]
    if moved:
        changes.append(f"versements déjà reçus ({moved:,.0f}) repris sur {new.number}".replace(",", " "))
    changes += revise(db, "invoice", new, user_id=user_id, **corrections)
    if new.total is not None and (new.paid or 0) > new.total + 0.005:
        changes.append((f"ATTENTION : le client a déjà versé plus que le nouveau total ({new.paid:,.0f} > {new.total:,.0f}) : "
                        "un remboursement ou un avoir est à prévoir").replace(",", " "))
    return new, changes


def dump(db: Session, kind: str, doc) -> dict:
    """Le document ouvert : statut, client, TVA, total et CHAQUE ligne (pour travailler dessus sans deviner)."""
    _model, item_model, fk, _col = KINDS[kind]
    items = db.query(item_model).filter(getattr(item_model, fk) == doc.id).order_by(item_model.position).all()
    lines = [{"n": i.position, "designation": i.description, "quantite": i.quantity, "unite": getattr(i, "unit", ""),
              "prix_unitaire": getattr(i, "unit_price", None), "total": getattr(i, "total", None)} for i in items]
    return {"numero": doc.number, "type": LABEL[kind], "statut": doc.status, "version": doc.version,
            "client": getattr(doc, "client_label", "") or getattr(doc, "customer_id", ""), "lieu": getattr(doc, "site_location", ""),
            "tva": getattr(doc, "vat_rate", None), "sous_total": getattr(doc, "subtotal", None), "total": getattr(doc, "total", None), "lignes": lines}


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
