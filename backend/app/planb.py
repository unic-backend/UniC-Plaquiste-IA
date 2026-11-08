"""Dossier Claude Code → serveur : les devis, factures et clients faits dans une session Claude Code (base locale restaurée d'une
sauvegarde) reviennent dans le serveur, pour n'avoir qu'UNE seule base.

Export (`scripts/planb_export.py`, dans la session Claude Code) : tout ce qui a été créé depuis la sauvegarde restaurée, en un fichier JSON.
Import (route /api/import/plan-a, bouton des Sauvegardes) : sûr et rejouable.
- Identifiants uniques (uuid) : un document déjà présent est reconnu et ignoré, rejouer un fichier ne crée jamais de doublon.
- Même numéro mais autre contenu = CONFLIT : rien n'est écrasé, le fichier dit lesquels (le patron décide).
- Un client déjà connu sous le même nom (autre fiche) est réutilisé. Rien n'est envoyé : tout arrive tel quel, brouillon compris.
- Les PDF sont refaits par le serveur avec le même code (même rendu qu'à l'origine).
- Hors périmètre : versements, bons de commande et de livraison, mémoire, pièces jointes (dit au patron, jamais oublié en silence).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, InvoiceItem, Quotation, QuotationItem

FORMAT = 1
APP = "UniC AI"
MAX_DOCS = 300
NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
ID_RE = re.compile(r"^[A-Za-z0-9-]{8,36}$")
# colonnes jamais reprises d'un fichier : références à des objets qui n'existent pas forcément ici, fichiers, ou propriété du serveur
_DROP = {"project_id", "artifact_id", "created_by", "approved_by"}


class PlanBError(ValueError):
    pass


def _cols(model) -> list[str]:
    return [c.key for c in sa_inspect(model).mapper.column_attrs]


def _plain(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _row(obj, model) -> dict:
    return {k: _plain(getattr(obj, k)) for k in _cols(model)}


def _utc(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def export_bundle(db: Session, since: datetime | None = None) -> dict:
    """Devis, factures et clients créés depuis `since` (la date de la sauvegarde restaurée), avec les clients dont ils dépendent."""
    def recent(model):
        q = db.query(model)
        return q.filter(model.created_at >= since) if since else q
    quotes = recent(Quotation).order_by(Quotation.created_at).all()
    invoices = recent(Invoice).order_by(Invoice.created_at).all()
    customers = {c.id: c for c in recent(Customer).all()}
    for doc in (*quotes, *invoices):
        if doc.customer_id and doc.customer_id not in customers:
            c = db.get(Customer, doc.customer_id)
            if c is not None:
                customers[c.id] = c
    return {"format": FORMAT, "app": APP, "created_at": datetime.now(timezone.utc).isoformat(),
            "since": since.isoformat() if since else None,
            "customers": [_row(c, Customer) for c in customers.values()],
            "quotes": [{**_row(q, Quotation), "items": [_row(i, QuotationItem) for i in q.items]} for q in quotes],
            "invoices": [{**_row(i, Invoice), "items": [_row(x, InvoiceItem) for x in i.items]} for i in invoices]}


def _clean(raw: dict, model, label: str, *, need_id: bool = True, drop: tuple = ()) -> dict:
    """Seules les colonnes connues du modèle (sans les références internes), chaque valeur ramenée à son type : un fichier
    trafiqué ou abîmé est refusé avec le champ en cause, jamais écrit tel quel."""
    if not isinstance(raw, dict):
        raise PlanBError(f"{label} : entrée illisible.")
    cols = sa_inspect(model).columns
    out = {k: v for k, v in raw.items() if k in set(_cols(model)) - _DROP - set(drop)}
    for k in list(out):
        kind, v = str(cols[k].type).upper(), out[k]
        try:
            if v is None:
                continue
            if kind.startswith(("DATETIME", "TIMESTAMP")):
                out[k] = _utc(v)
            elif kind.startswith("FLOAT"):
                out[k] = float(v)
            elif kind.startswith("INTEGER"):
                out[k] = int(v)
            elif kind.startswith("BOOLEAN"):
                out[k] = bool(v)
            else:
                out[k] = str(v)
        except (TypeError, ValueError):
            raise PlanBError(f"{label} : « {k} » illisible.") from None
    if need_id and not ID_RE.match(str(out.get("id") or "")):
        raise PlanBError(f"{label} : identifiant manquant ou invalide.")
    if not need_id:
        out.pop("id", None)   # lignes : nouveaux identifiants côté serveur (aucune collision possible)
    return out


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def import_bundle(db: Session, bundle: dict, user_id: str | None) -> dict:
    """Importe un dossier. Renvoie ce qui est créé, déjà présent, en conflit ou laissé de côté. Tout ou rien pour les écritures :
    une erreur imprévue annule l'import entier (rien n'est à moitié importé)."""
    from app import services
    if not isinstance(bundle, dict) or bundle.get("app") != APP or bundle.get("format") != FORMAT:
        raise PlanBError("Ce fichier n'est pas un dossier UniC (format ou application inconnus).")
    quotes, invoices, customers = (bundle.get(k) or [] for k in ("quotes", "invoices", "customers"))
    if not all(isinstance(x, list) for x in (quotes, invoices, customers)):
        raise PlanBError("Dossier illisible : listes attendues.")
    if len(quotes) + len(invoices) > MAX_DOCS or len(customers) > MAX_DOCS:
        raise PlanBError(f"Dossier trop gros (plus de {MAX_DOCS} documents) : découpe-le.")
    rep: dict[str, list] = {"clients_crees": [], "clients_reutilises": [], "devis_crees": [], "devis_deja_la": [], "factures_creees": [],
                            "factures_deja_la": [], "conflits": [], "ignores": []}
    new_pdf: list = []
    cmap: dict[str, str | None] = {}
    try:
        for raw in customers:
            c = _clean(raw, Customer, "Client")
            if db.get(Customer, c["id"]) is not None:
                cmap[c["id"]] = c["id"]
                continue
            twin = next((x for x in db.query(Customer).filter(Customer.name.ilike(c.get("name") or "")).all()
                         if _norm(x.name) == _norm(c.get("name"))), None)
            if twin is not None:
                cmap[c["id"]] = twin.id
                rep["clients_reutilises"].append(c.get("name"))
                continue
            c["code"] = next_free_code(db, c.get("code"))
            db.add(Customer(**c, created_by=user_id))
            db.flush()
            cmap[c["id"]] = c["id"]
            rep["clients_crees"].append(c.get("name"))
        for raw in quotes:
            items = raw.get("items") if isinstance(raw, dict) and isinstance(raw.get("items"), list) else []
            q = _clean(raw, Quotation, "Devis")
            num = str(q.get("number") or "")
            if not NUMBER_RE.match(num):
                raise PlanBError(f"Devis {q['id']} : numéro invalide.")
            have = db.query(Quotation).filter(Quotation.number == num).first()
            if have is not None:
                (rep["devis_deja_la"] if have.id == q["id"] else rep["conflits"]).append(
                    num if have.id == q["id"] else {"numero": num, "raison": "ce numéro existe déjà dans le serveur avec un autre devis : rien n'est écrasé"})
                continue
            if db.get(Quotation, q["id"]) is not None:
                rep["conflits"].append({"numero": num, "raison": "identifiant déjà pris par un autre devis"})
                continue
            q["customer_id"] = cmap.get(q.get("customer_id"))
            row = Quotation(**q, created_by=user_id, approved_by=user_id if q.get("approved_at") else None)
            row.items = [QuotationItem(**_clean(i, QuotationItem, "Ligne de devis", need_id=False, drop=("quotation_id",))) for i in items]
            db.add(row)
            db.flush()
            new_pdf.append(row)
            rep["devis_crees"].append(num)
        for raw in invoices:
            items = raw.get("items") if isinstance(raw, dict) and isinstance(raw.get("items"), list) else []
            inv = _clean(raw, Invoice, "Facture")
            num = str(inv.get("number") or "")
            if not NUMBER_RE.match(num):
                raise PlanBError(f"Facture {inv['id']} : numéro invalide.")
            have = db.query(Invoice).filter(Invoice.number == num).first()
            if have is not None:
                (rep["factures_deja_la"] if have.id == inv["id"] else rep["conflits"]).append(
                    num if have.id == inv["id"] else {"numero": num, "raison": "ce numéro existe déjà dans le serveur avec une autre facture : rien n'est écrasé"})
                continue
            if db.get(Invoice, inv["id"]) is not None:
                rep["conflits"].append({"numero": num, "raison": "identifiant déjà pris par une autre facture"})
                continue
            inv["customer_id"] = cmap.get(inv.get("customer_id"))
            if inv.get("quotation_id") and db.get(Quotation, inv["quotation_id"]) is None:
                inv["quotation_id"] = None   # le devis d'origine n'est pas dans le serveur : la facture reste valable seule
            if inv.get("corrects_id") and db.query(Invoice).filter(Invoice.id == inv["corrects_id"]).first() is None:
                inv["corrects_id"] = None
            row = Invoice(**inv, created_by=user_id, approved_by=user_id if inv.get("approved_at") else None)
            row.items = [InvoiceItem(**_clean(i, InvoiceItem, "Ligne de facture", need_id=False, drop=("invoice_id",))) for i in items]
            db.add(row)
            db.flush()
            new_pdf.append(row)
            rep["factures_creees"].append(num)
        for key in ("payments", "purchase_orders", "delivery_notes"):
            if bundle.get(key):
                rep["ignores"].append(f"{key} : pas repris par cet import")
        for row in new_pdf:   # PDF refait par le serveur, même code qu'à l'origine ; un échec n'annule pas l'import (le PDF se refait à l'ouverture)
            try:
                art = services.generate_quote_pdf(db, row, user_id) if isinstance(row, Quotation) else services.generate_invoice_pdf(db, row, user_id)
                row.artifact_id = art.id
            except Exception as exc:   # noqa: BLE001
                rep["ignores"].append(f"PDF de {row.number} : {type(exc).__name__}")
        services.audit(db, user_id, "import_plan_a", "import", "plan-a",
                       f"{len(rep['devis_crees'])} devis, {len(rep['factures_creees'])} factures, {len(rep['conflits'])} conflit(s)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return rep


def next_free_code(db: Session, wanted: str | None) -> str:
    """Code client : celui du fichier s'il est libre, sinon le prochain du serveur (le code est unique)."""
    from app.services import next_number
    if wanted and db.query(Customer).filter(Customer.code == wanted).first() is None:
        return wanted
    return next_number(db, "customer")
