"""Services métier : numérotation, documents, tarifs, audit."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Artifact,
    AuditLog,
    CompanySettings,
    Customer,
    DeliveryNote,
    DeliveryNoteItem,
    Invoice,
    InvoiceItem,
    Material,
    MaterialPrice,
    Payment,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Quotation,
    QuotationItem,
    Sequence,
    Supplier,
    utcnow,
)
from app.pdfs import build_document_pdf, fr_num, money, validate_pdf


PREFIX = {
    "quote": "DEV",
    "invoice": "FAC",
    "credit": "AVO",
    "po": "BC",
    "dn": "BL",
    "report": "RAP",
    "customer": "CLI",
    "supplier": "FRN",
    "project": "PRJ",
}


def next_number(db: Session, kind: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = db.get(Sequence, (kind, year))
    if seq is None:
        seq = Sequence(name=kind, year=year, value=0)
        db.add(seq)
        db.flush()
    seq.value += 1
    prefix = PREFIX.get(kind, kind.upper()[:3])
    return f"{prefix}-{year}-{seq.value:04d}"


# ---------- numérotation maison : UC-AAAA-MMJJ-CLI ----------
# CLI = initiales (prénom + nom) du client. Règle du propriétaire : « Ousmane Diop » → OD,
# « Fast Group » → FG. Jamais un code fixe. XXX = client inconnu (trou visible, pas un identifiant).

UNKNOWN_SUFFIX = "XXX"
MAX_INITIALS = 3
SINGLE_WORD_LETTERS = 3
_SEPARATORS = re.compile(r"[\s\-_'’.]+")
_LINK_WORDS = frozenset({"de", "du", "des", "la", "le", "les", "et", "d", "l", "au", "aux", "a"})
_ACCENTS = str.maketrans("àâäáãåçéèêëíìîïñóòôöõúùûüýÿ", "aaaaaaceeeeiiiinooooouuuuyy")


def client_initials(name: str | None) -> str:
    """« Ousmane Diop » → OD ; « Jean-Pierre Ndiaye » → JPN ; « Sonatel » → SON ; vide → XXX."""
    clean = str(name or "").strip().lower().translate(_ACCENTS)
    words = [w for w in _SEPARATORS.split(clean) if w.isalnum()]
    if not words:
        return UNKNOWN_SUFFIX
    carriers = [w for w in words if w not in _LINK_WORDS]
    if len(carriers) >= 2:
        words = carriers
    if len(words) == 1:
        return words[0][:SINGLE_WORD_LETTERS].upper()
    return "".join(w[0] for w in words[:MAX_INITIALS]).upper()


def _taken_numbers(db: Session, prefix: str) -> set[str]:
    out: set[str] = set()
    for model in (Quotation, Invoice, PurchaseOrder, DeliveryNote):
        out.update(n for (n,) in db.query(model.number).filter(model.number.like(f"{prefix}%")).all())
    return out


def _norm_name(name: str | None) -> str:
    return " ".join(sorted(w for w in _SEPARATORS.split(str(name or "").strip().lower().translate(_ACCENTS)) if w))


def _quote_client(q: Quotation) -> str:
    return _norm_name(q.customer.name if q.customer else q.client_label)


NUMBER_RE = _NUMBER_RE = re.compile(r"^UC-(\d{4})-(\d{4})-([A-Z]+)(\d*)$")


def same_site(a: str | None, b: str | None) -> bool:
    """Deux lieux de chantier désignent le même endroit : égaux ou l'un contient l'autre (« Point E » / « Point E, appt A »).
    Un lieu vide est compatible avec tout : il ne sépare jamais deux clients."""
    def words(v) -> set[str]:
        return {w for w in re.split(r"[^a-z0-9]+", str(v or "").lower().translate(_ACCENTS)) if w and w not in _LINK_WORDS}

    x, y = words(a), words(b)
    if not x or not y:
        return True
    return x <= y or y <= x


def same_party(name_a: str | None, site_a: str | None, name_b: str | None, site_b: str | None) -> bool:
    """Même client = même nom ET même lieu. Deux « Madame Ribeiro » à deux adresses sont deux clients."""
    na, nb = _norm_name(name_a), _norm_name(name_b)
    return bool(na) and na == nb and same_site(site_a, site_b)


def sites_of_client(db: Session, name: str | None) -> list[str]:
    """Lieux distincts (non vides) déjà utilisés par les devis de ce nom de client."""
    out: list[str] = []
    for q in db.query(Quotation).filter(Quotation.site_location != "").all():
        if _norm_name(q.customer.name if q.customer else q.client_label) == _norm_name(name) \
                and not any(same_site(q.site_location, o) for o in out):
            out.append(q.site_location)
    return out


def quote_signature(q: Quotation) -> tuple:
    """Ce que le devis vend : lignes (désignation, quantité, unité). Deux devis de même signature sont le même travail."""
    return tuple(sorted(((it.description or "").strip().lower(), round(it.quantity or 0, 3), (it.unit or "").lower())
                        for it in q.items))


def _client_block(db: Session, party_name: str | None, day: date, lieu: str | None = None) -> int:
    """Le bloc à 4 chiffres (« 1004 ») appartient au CLIENT (nom + lieu du chantier) : Pape Diop 1004, Awa Fall 1005,
    même le même jour ; le lendemain on continue (1007…). Un client qui revient garde SON bloc (le devis suivant prend 2, 3…).
    Deux clients de même nom mais de lieux différents ont chacun leur bloc."""
    me, init = _norm_name(party_name), client_initials(party_name)
    owners: dict[int, list[tuple[str, str]]] = {}
    for (number, label, cust_name, site) in (
        (q.number, q.client_label, q.customer.name if q.customer else None, q.site_location)
        for q in db.query(Quotation).filter(Quotation.number.like(f"UC-{day.year}-%")).all()
    ):
        m = _NUMBER_RE.match(number)
        if not m:
            continue
        block = int(m.group(2))
        owner = _norm_name(cust_name or label)
        if not owner and m.group(3) == init:
            owner = me   # devis ancien sans nom de client, mêmes initiales : on le rattache à ce client
        owners.setdefault(block, []).append((owner, site or ""))
    if me:
        mine = [b for b, o in owners.items() if any(n == me and same_site(site, lieu) for n, site in o)]
        if mine:
            return min(mine)
    block = int(f"{day.month:02d}{day.day:02d}")
    while block in owners:
        block += 1
    return block


def _client_root(db: Session, party_name: str | None, day: date, lieu: str | None = None) -> str:
    return f"UC-{day.year}-{_client_block(db, party_name, day, lieu):04d}-{client_initials(party_name)}"


def document_number(db: Session, party_name: str | None, on: date | None = None, lieu: str | None = None) -> str:
    """UC-AAAA-BLOC-CLI. Chaque client a SON bloc (1004, 1005, 1006… dans l'ordre d'arrivée) ; son devis suivant
    garde le même bloc et prend 2, 3… (UC-2026-1004-PD2). Deux clients ne partagent jamais un numéro."""
    day = on or datetime.now(timezone.utc).date()
    base = _client_root(db, party_name, day, lieu)
    taken = _taken_numbers(db, base)
    number, i = base, 2
    while number in taken:
        number = f"{base}{i}"
        i += 1
    return number


def client_name_of(db: Session, doc) -> str:
    """Client d'un document : sa fiche, son nom saisi, ou celui du devis dont il découle (facture, bon)."""
    if isinstance(doc, Quotation):
        return (doc.customer.name if doc.customer else doc.client_label) or ""
    cust = getattr(doc, "customer", None)
    if cust is not None:
        return cust.name
    qid = getattr(doc, "quotation_id", None)
    quote = db.get(Quotation, qid) if qid else None
    if quote is None:   # bon de commande / de livraison : numéro du devis + « -BC », « -BL »
        root = re.sub(r"-(BC|BL|F|AV)\d*$", "", doc.number or "")
        quote = db.query(Quotation).filter(Quotation.number == root).first() if root != doc.number else None
    return client_name_of(db, quote) if quote is not None else ""


def search_documents(db: Session, query: str = "", kind: str = "all", min_total: float | None = None,
                     max_total: float | None = None, limit: int = 30) -> list[dict]:
    """Retrouve des documents par client (prénom/nom dans n'importe quel ordre, sans accents), numéro ou titre."""
    models = {"quote": Quotation, "invoice": Invoice, "po": PurchaseOrder, "dn": DeliveryNote}
    wanted = models if kind in ("all", "", None) else {kind: models[kind]}
    words = [w for w in _SEPARATORS.split(str(query or "").lower().translate(_ACCENTS)) if w]
    out = []
    for k, model in wanted.items():
        for r in db.query(model).order_by(model.created_at.desc()).all():
            who = client_name_of(db, r)
            hay = f"{who} {r.number} {r.title}".lower().translate(_ACCENTS)
            if not all(w in hay for w in words):
                continue
            total = getattr(r, "total", None)
            if min_total is not None and not (total is not None and total >= min_total):
                continue
            if max_total is not None and not (total is not None and total <= max_total):
                continue
            out.append({"kind": k, "id": r.id, "numero": r.number, "client": who, "statut": r.status, "total": total,
                        "objet": (getattr(r, "object_text", "") or r.title or "")[:160],
                        "date": r.created_at.date().isoformat() if r.created_at else None, "_t": r.created_at})
    out.sort(key=lambda x: x["_t"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for x in out:
        x.pop("_t", None)
    return out[:limit]


DOC_CODES = {"invoice": "F", "credit": "AV", "po": "BC", "dn": "BL"}


def linked_number(db: Session, code: str, *, quote_number: str | None = None,
                  party_name: str | None = None, on: date | None = None) -> str:
    """Numéro d'un document lié à un devis : « numéro du devis » + « -BC / -BL / -F / -AV ».

    UC-2026-0714-OD (devis) → UC-2026-0714-OD-BC, -BL, -F. Ressemble au devis, ne s'y confond jamais.
    Plusieurs du même type : -BC2, -BC3. Sans devis : racine date + initiales du client."""
    if quote_number:
        root = quote_number
    else:
        day = on or datetime.now(timezone.utc).date()
        root = _client_root(db, party_name, day)
    taken = _taken_numbers(db, root)
    number, i = f"{root}-{code}", 2
    while number in taken:
        number = f"{root}-{code}{i}"
        i += 1
    return number


def company_dict(db: Session) -> dict:
    row = db.query(CompanySettings).first()
    if row is None:
        return {"name": "UniC Plaquiste"}
    return {
        "name": row.name,
        "legal_name": row.legal_name,
        "address": row.address,
        "city": row.city,
        "country": row.country,
        "phone": row.phone,
        "email": row.email,
        "tax_id": row.tax_id,
        "currency": row.currency,
        "vat_rate": row.vat_rate,
        "quote_validity_days": row.quote_validity_days,
        "invoice_due_days": row.invoice_due_days if row.invoice_due_days is not None else 15,
        "payment_terms": row.payment_terms,
        "default_waste": row.default_waste,
        "default_margin": row.default_margin,
        "board_width_m": row.board_width_m,
        "board_height_m": row.board_height_m,
        "stud_spacing_m": row.stud_spacing_m,
        "website": row.website,
        "notes": row.notes,
    }


def audit(db: Session, user_id: str | None, action: str, entity_type: str, entity_id: str, details: str = ""):
    db.add(AuditLog(
        user_id=user_id, action=action, entity_type=entity_type,
        entity_id=entity_id, details=details[:4000],
    ))


def current_price(db: Session, material_id: str, kind: str) -> MaterialPrice | None:
    now = utcnow()
    q = (
        db.query(MaterialPrice)
        .filter(MaterialPrice.material_id == material_id, MaterialPrice.kind == kind)
        .filter(MaterialPrice.valid_from <= now)
        .order_by(MaterialPrice.valid_from.desc())
    )
    for p in q.all():
        if p.valid_to is None or p.valid_to >= now:
            return p
    return None


def selling_price_for_sku(db: Session, sku: str) -> tuple[float | None, str]:
    mat = db.query(Material).filter(Material.sku == sku).first()
    if mat is None:
        return None, "matériau absent du catalogue UniC"
    price = current_price(db, mat.id, "selling")
    if price is None:
        return None, "prix de vente non renseigné dans la base UniC"
    return price.amount, "prix UniC"


def material_by_sku(db: Session, sku: str) -> Material | None:
    return db.query(Material).filter(Material.sku == sku).first()


def party_text_customer(c: Customer | None, label: str = "") -> str:
    if c is None:
        return f"{label}\n(coordonnées à renseigner)" if label else "Client non renseigné (non inventé)."
    parts = [c.name]
    if c.contact_name:
        parts.append(c.contact_name)
    if c.address:
        parts.append(c.address)
    if c.city:
        parts.append(c.city)
    if c.phone:
        parts.append(f"Tél. {c.phone}")
    if c.email:
        parts.append(c.email)
    return "\n".join(parts)


def party_text_supplier(s: Supplier | None) -> str:
    if s is None:
        return "Fournisseur non renseigné (non inventé)."
    parts = [s.name]
    if s.contact_name:
        parts.append(s.contact_name)
    if s.address:
        parts.append(s.address)
    if s.phone:
        parts.append(f"Tél. {s.phone}")
    if s.email:
        parts.append(s.email)
    return "\n".join(parts)


def store_artifact(db: Session, path: Path, filename: str, entity_type: str, entity_id: str,
                   key: str, user_id: str | None, mime: str = "application/pdf") -> Artifact:
    if not validate_pdf(path) and mime == "application/pdf":
        raise RuntimeError("PDF invalide après génération")
    existing = db.query(Artifact).filter(Artifact.artifact_key == key).first()
    if existing is not None:   # même document corrigé : on remplace le PDF, on n'en empile pas un second
        existing.filename, existing.path, existing.size = filename, str(path), path.stat().st_size
        existing.version += 1
        db.flush()
        return existing
    art = Artifact(
        artifact_key=key,
        filename=filename,
        mime_type=mime,
        path=str(path),
        size=path.stat().st_size,
        status="ready",
        entity_type=entity_type,
        entity_id=entity_id,
        created_by=user_id,
    )
    db.add(art)
    db.flush()
    return art


_UNSET = object()  # « TVA non précisée » ≠ « pas de TVA » (None)


def quotation_from_quantities(
    db: Session,
    *,
    title: str,
    quantities: list[dict],
    customer_id: str | None,
    project_id: str | None,
    user_id: str | None,
    notes: str = "",
    assumptions: list[str] | None = None,
    missing: list[str] | None = None,
    client_name: str | None = None,
    vat_rate: float | None | object = _UNSET,
    objet: str = "",
    lieu: str = "",
) -> Quotation:
    company = company_dict(db)
    known = db.get(Customer, customer_id) if customer_id else None
    label = (known.name if known else (client_name or "")).strip()
    number = document_number(db, label, lieu=lieu)
    q = Quotation(
        number=number,
        client_label="" if known else label,
        customer_id=customer_id,
        project_id=project_id,
        title=title or f"Devis {number}",
        object_text=(objet or "").strip()[:900],
        site_location=(lieu or "").strip()[:255],
        status="draft",
        currency=company.get("currency") or "",
        vat_rate=company.get("vat_rate") if vat_rate is _UNSET else vat_rate,
        validity_days=company.get("quote_validity_days") or 30,
        payment_terms=company.get("payment_terms") or "",
        notes=notes,
        assumptions="\n".join(assumptions or []),
        missing_info="\n".join(missing or []),
        created_by=user_id,
    )
    db.add(q)
    db.flush()
    subtotal = 0.0
    complete = True
    any_price = False
    for i, line in enumerate(quantities, start=1):
        sku = line.get("sku") or ""
        mat = material_by_sku(db, sku) if sku else None
        unit_price, _reason = (None, "")
        if mat:
            unit_price, _reason = selling_price_for_sku(db, sku)
        qty = float(line.get("quantity") or 0)
        total = None
        if unit_price is None:
            complete = False
        else:
            total = round(qty * unit_price, 2)
            subtotal += total
            any_price = True
        db.add(QuotationItem(
            quotation_id=q.id,
            position=i,
            description=line.get("name") or line.get("description") or sku,
            quantity=qty,
            unit=line.get("unit") or "u",
            unit_price=unit_price,
            total=total,
            material_id=mat.id if mat else None,
            data_status=line.get("status") or "estimated",
            formula=line.get("formula") or "",
            notes=line.get("notes") or "",
        ))
    q.prices_complete = complete and any_price
    if any_price:
        q.subtotal = round(subtotal, 2)
        if q.vat_rate is not None:
            q.vat_amount = round(subtotal * q.vat_rate, 2)
            q.total = round(subtotal + q.vat_amount, 2)
        else:
            q.total = q.subtotal
    else:
        q.subtotal = None
        q.vat_amount = None
        q.total = None
        q.prices_complete = False
    db.flush()
    generate_quote_pdf(db, q, user_id)
    audit(db, user_id, "create_quote", "quotation", q.id, q.number)
    db.commit()
    db.refresh(q)
    return q


def generate_quote_pdf(db: Session, q: Quotation, user_id: str | None) -> Artifact:
    db.flush()
    db.expire(q, ["items"])   # les lignes ajoutées à l'instant doivent figurer sur le PDF
    company = company_dict(db)
    customer = db.get(Customer, q.customer_id) if q.customer_id else None
    project = db.get(Project, q.project_id) if q.project_id else None
    items = sorted(q.items, key=lambda x: x.position)
    currency = q.currency or company.get("currency") or ""
    rows = []
    for it in items:
        rows.append([
            str(it.position),
            it.description,
            fr_num(it.quantity, 2),
            it.unit,
            money(it.unit_price, currency),
            money(it.total, currency),
        ])
    totals = []
    if q.subtotal is not None:
        totals.append(("Sous-total HT", money(q.subtotal, currency)))
        if q.vat_rate is not None:
            totals.append((f"TVA {fr_num(q.vat_rate * 100, 1)} %", money(q.vat_amount, currency)))
        totals.append(("Total", money(q.total, currency)))
    else:
        totals.append(("Total", "incomplet — prix manquants"))
    warnings = []
    if not q.prices_complete:
        warnings.append("Des prix UniC sont manquants. Aucun tarif n'a été inventé. Total incomplet.")
    filename = f"UniC_Devis_{q.number.replace('-', '_')}.pdf"
    key = f"unic-quote-{q.number.lower()}"
    dest = settings.artifacts_path / "quotes" / filename
    meta = [
        f"N° {q.number}",
        f"Date {q.created_at.strftime('%d/%m/%Y') if q.created_at else ''}",
        f"Validité {q.validity_days} jours",
    ]
    extra = []   # hypothèses et infos manquantes restent dans la conversation, pas sur le devis du client
    build_document_pdf(
        dest,
        company=company,
        doc_label="DEVIS",
        number=q.number,
        title=q.object_text or q.title or f"Devis {q.number}",
        status=q.status,
        meta_lines=meta,
        party_left=("Émetteur", party_text_from_company(company)),
        party_right=("Client", (party_text_customer(customer) if customer else (q.client_label or "Client non renseigné"))
                     + (f"\nLieu du chantier : {q.site_location or project.name}" if (q.site_location or project) else "")),
        headers=["#", "Désignation", "Qté", "Unité", "P.U.", "Total"],
        rows=rows,
        col_widths=[18, 210, 50, 40, 80, 80],
        totals=totals,
        notes=q.notes,
        warnings=warnings,
        extra_paragraphs=extra,
    )
    art = store_artifact(db, dest, filename, "quotation", q.id, key, user_id)
    q.artifact_id = art.id
    return art


def party_text_from_company(company: dict) -> str:
    parts = [company.get("name") or "UniC Plaquiste"]
    for k in ("legal_name", "address", "city", "country", "phone", "email", "tax_id"):
        v = (company.get(k) or "").strip()
        if v:
            parts.append(v)
    if len(parts) == 1:
        parts.append("Coordonnées à renseigner dans Paramètres.")
    return "\n".join(parts)


def invoice_from_quote(db: Session, quote: Quotation, kind: str, user_id: str | None) -> Invoice:
    number = linked_number(db, DOC_CODES["credit" if kind == "credit" else "invoice"], quote_number=quote.number)
    inv = Invoice(
        number=number,
        kind=kind,
        customer_id=quote.customer_id,
        project_id=quote.project_id,
        quotation_id=quote.id,
        title=quote.title,
        status="draft",
        currency=quote.currency,
        subtotal=quote.subtotal,
        vat_rate=quote.vat_rate,
        vat_amount=quote.vat_amount,
        total=quote.total,
        paid=0,
        remaining=quote.total,
        notes=f"Issue du devis {quote.number}",
        created_by=user_id,
    )
    db.add(inv)
    db.flush()
    for it in sorted(quote.items, key=lambda x: x.position):
        db.add(InvoiceItem(
            invoice_id=inv.id,
            position=it.position,
            description=it.description,
            quantity=it.quantity,
            unit=it.unit,
            unit_price=it.unit_price,
            total=it.total,
        ))
    generate_invoice_pdf(db, inv, user_id)
    audit(db, user_id, "create_invoice", "invoice", inv.id, inv.number)
    db.commit()
    db.refresh(inv)
    return inv


def generate_invoice_pdf(db: Session, inv: Invoice, user_id: str | None) -> Artifact:
    db.flush()
    db.expire(inv, ["items"])   # les lignes ajoutées à l'instant doivent figurer sur le PDF
    company = company_dict(db)
    customer = db.get(Customer, inv.customer_id) if inv.customer_id else None
    currency = inv.currency or company.get("currency") or ""
    items = sorted(inv.items, key=lambda x: x.position)
    rows = [[
        str(it.position), it.description, fr_num(it.quantity, 2), it.unit,
        money(it.unit_price, currency), money(it.total, currency),
    ] for it in items]
    totals = []
    if inv.subtotal is not None:
        totals.append(("Sous-total HT", money(inv.subtotal, currency)))
        if inv.vat_rate is not None:
            totals.append(("TVA", money(inv.vat_amount, currency)))
        totals.append(("Total", money(inv.total, currency)))
        totals.append(("Payé", money(inv.paid, currency)))
        totals.append(("Reste dû", money(inv.remaining if inv.remaining is not None else None, currency)))
    warnings = []
    if inv.total is None:
        warnings.append("Total incomplet : prix manquants dans la base UniC.")
    kind_label = {
        "invoice": "FACTURE",
        "deposit": "FACTURE D'ACOMPTE",
        "partial": "SITUATION / FACTURE PARTIELLE",
        "final": "FACTURE DE SOLDE",
        "credit": "AVOIR",
    }.get(inv.kind, "FACTURE")
    filename = f"UniC_Facture_{inv.number.replace('-', '_')}.pdf"
    dest = settings.artifacts_path / "invoices" / filename
    build_document_pdf(
        dest, company=company, doc_label=kind_label, number=inv.number,
        title=inv.title or kind_label, status=inv.status,
        meta_lines=[f"N° {inv.number}", f"Date {inv.created_at.strftime('%d/%m/%Y') if inv.created_at else ''}",
                    "Type : " + {"invoice": "Facture", "deposit": "Acompte", "partial": "Situation", "final": "Solde", "credit": "Avoir"}.get(inv.kind, "Facture")],
        party_left=("Émetteur", party_text_from_company(company)),
        party_right=("Client", party_text_customer(customer)),
        headers=["#", "Désignation", "Qté", "Unité", "P.U.", "Total"],
        rows=rows, col_widths=[18, 210, 50, 40, 80, 80],
        totals=totals, notes=inv.notes, warnings=warnings,
    )
    art = store_artifact(db, dest, filename, "invoice", inv.id, f"unic-invoice-{inv.number.lower()}", user_id)
    inv.artifact_id = art.id
    return art


def reliquat_data(db: Session, inv: Invoice) -> dict:
    """Le reliquat d'une affaire : ce qui a été convenu (devis), ce que le client a versé (tous les paiements des factures du devis),
    ce qui reste à payer. Sans devis lié, la facture elle-même fait foi."""
    quote = db.get(Quotation, inv.quotation_id) if inv.quotation_id else None
    invoices = [inv]
    if quote is not None:
        invoices = db.query(Invoice).filter(Invoice.quotation_id == quote.id, Invoice.kind != "credit").all() or [inv]
    credits = db.query(Invoice).filter(Invoice.quotation_id == quote.id, Invoice.kind == "credit").all() if quote is not None else []
    agreed = quote.total if quote is not None and quote.total is not None else inv.total
    if agreed is not None and credits:
        agreed -= sum((c.total or 0) for c in credits)
    pays = sorted((p for i in invoices for p in i.payments), key=lambda p: p.paid_at or utcnow())
    paid = sum(p.amount or 0 for p in pays)
    return {"quote": quote, "invoices": invoices, "payments": pays, "agreed": agreed, "paid": paid,
            "remaining": None if agreed is None else max(0.0, agreed - paid), "credits": sum((c.total or 0) for c in credits)}


def balance_message(db: Session, inv: Invoice, client: str, currency: str, phone: str = "") -> str:
    """Message de rappel : convenu, versé, reste à payer (aucune IA : uniquement les chiffres du dossier)."""
    d = reliquat_data(db, inv)

    def amt(v: float | None) -> str:
        return f"{(v or 0):,.0f} {currency or 'FCFA'}".replace(",", " ")
    first = (client or "").strip()
    ref = d["quote"].number if d["quote"] is not None else inv.number
    lines = [f"Bonjour{(' ' + first) if first else ''},", "",
             f"Voici le point sur votre dossier {ref} : montant convenu {amt(d['agreed'])}, déjà versé {amt(d['paid'])}.",
             f"Il reste {amt(d['remaining'])} à régler.", "Le reliquat détaillé est joint à ce message.",
             "Merci d'avance et bonne journée.", "", "UniC Plaquiste"]
    if phone:
        lines.append(phone)
    return "\n".join(lines)


def build_balance_pdf(db: Session, inv: Invoice) -> Path:
    """RELIQUAT : 1) ce qui a été convenu, 2) ce que le client a versé, 3) ce qui reste à payer. Recalculé à chaque demande."""
    company = company_dict(db)
    customer = db.get(Customer, inv.customer_id) if inv.customer_id else None
    currency = inv.currency or company.get("currency") or ""
    d = reliquat_data(db, inv)
    quote = d["quote"]
    sec = lambda t: ["", f"<b>{t}</b>", "", "", "", ""]
    rows = [sec("1. CE QUI A ÉTÉ CONVENU" + (f" — devis {quote.number}" if quote is not None else f" — facture {inv.number}"))]
    src = sorted(quote.items, key=lambda x: x.position) if quote is not None else sorted(inv.items, key=lambda x: x.position)
    for it in src:
        rows.append([str(it.position), it.description, fr_num(it.quantity, 2), it.unit, money(it.unit_price, currency), money(it.total, currency)])
    if d["credits"]:
        rows.append(["", "Avoirs accordés", "", "", "", "- " + money(d["credits"], currency)])
    rows.append(["", "<b>MONTANT CONVENU</b>", "", "", "", f"<b>{money(d['agreed'], currency)}</b>"])
    rows.append(sec("2. CE QUE LE CLIENT A VERSÉ"))
    if d["payments"]:
        for p in d["payments"]:
            inv_no = next((i.number for i in d["invoices"] if p.invoice_id == i.id), "")
            how = " — ".join(x for x in ((p.method or "").strip(), (p.reference or "").strip(), f"facture {inv_no}" if len(d["invoices"]) > 1 else "") if x)
            rows.append(["", f"Versement du {p.paid_at.strftime('%d/%m/%Y') if p.paid_at else ''}" + (f" ({how})" if how else ""), "", "", "", money(p.amount, currency)])
    else:
        rows.append(["", "Aucun versement enregistré", "", "", "", ""])
    rows.append(["", "<b>TOTAL VERSÉ</b>", "", "", "", f"<b>{money(d['paid'], currency)}</b>"])
    totals = [("Montant convenu", money(d["agreed"], currency)), ("Déjà versé", money(d["paid"], currency)),
              ("RESTE À PAYER", money(d["remaining"], currency))]
    ref = quote.number if quote is not None else inv.number
    filename = f"UniC_Reliquat_{ref.replace('-', '_')}.pdf"
    dest = settings.artifacts_path / "balances" / filename
    build_document_pdf(
        dest, company=company, doc_label="RELIQUAT", number=ref, title=(quote.object_text or quote.title) if quote is not None and (quote.object_text or quote.title) else f"Reliquat — {ref}",
        status="",
        meta_lines=[f"Dossier {ref}", f"Édité le {utcnow().strftime('%d/%m/%Y')}"] + ([f"Chantier : {quote.site_location}"] if quote is not None and quote.site_location else []),
        party_left=("Émetteur", party_text_from_company(company)), party_right=("Client", party_text_customer(customer)),
        headers=["#", "Désignation", "Qté", "Unité", "P.U.", "Total"], rows=rows, col_widths=[18, 210, 50, 40, 80, 80],
        totals=totals, notes="", warnings=[],
    )
    return dest


def create_purchase_order(db: Session, *, title: str, quantities: list[dict],
                          supplier_id: str | None, project_id: str | None, user_id: str | None,
                          notes: str = "", quote_number: str | None = None,
                          client_name: str | None = None) -> PurchaseOrder:
    company = company_dict(db)
    number = linked_number(db, DOC_CODES["po"], quote_number=quote_number, party_name=client_name)
    po = PurchaseOrder(
        number=number, supplier_id=supplier_id, project_id=project_id,
        title=title or f"Bon de commande {number}", status="draft",
        currency=company.get("currency") or "", notes=notes, created_by=user_id,
    )
    db.add(po)
    db.flush()
    subtotal = 0.0
    any_price = True
    for i, line in enumerate(quantities, start=1):
        sku = line.get("sku") or ""
        mat = material_by_sku(db, sku) if sku else None
        unit_price = None
        if mat:
            p = current_price(db, mat.id, "purchase")
            if p:
                unit_price = p.amount
        qty = float(line.get("quantity") or 0)
        total = round(qty * unit_price, 2) if unit_price is not None else None
        if total is None:
            any_price = False
        else:
            subtotal += total
        db.add(PurchaseOrderItem(
            order_id=po.id, position=i,
            description=line.get("name") or line.get("description") or sku,
            quantity=qty, unit=line.get("unit") or "u",
            unit_price=unit_price, total=total,
            material_id=mat.id if mat else None,
        ))
    po.total = round(subtotal, 2) if any_price else None
    generate_po_pdf(db, po, user_id)
    audit(db, user_id, "create_po", "purchase_order", po.id, po.number)
    db.commit()
    db.refresh(po)
    return po


def generate_po_pdf(db: Session, po: PurchaseOrder, user_id: str | None) -> Artifact:
    db.flush()
    db.expire(po, ["items"])   # les lignes ajoutées à l'instant doivent figurer sur le PDF
    company = company_dict(db)
    supplier = db.get(Supplier, po.supplier_id) if po.supplier_id else None
    currency = po.currency or ""
    items = sorted(po.items, key=lambda x: x.position)
    rows = [[
        str(it.position), it.description, fr_num(it.quantity, 2), it.unit,
        money(it.unit_price, currency), money(it.total, currency),
    ] for it in items]
    totals = [("Total", money(po.total, currency) if po.total is not None else "incomplet — prix d'achat manquants")]
    warnings = []
    if po.total is None:
        warnings.append("Prix d'achat UniC manquants. Aucun tarif n'a été inventé.")
    filename = f"UniC_BC_{po.number.replace('-', '_')}.pdf"
    dest = settings.artifacts_path / "orders" / filename
    build_document_pdf(
        dest, company=company, doc_label="BON DE COMMANDE", number=po.number,
        title=po.title, status=po.status,
        meta_lines=[f"N° {po.number}", f"Date {po.created_at.strftime('%d/%m/%Y') if po.created_at else ''}"],
        party_left=("Acheteur", party_text_from_company(company)),
        party_right=("Fournisseur", party_text_supplier(supplier)),
        headers=["#", "Désignation", "Qté", "Unité", "P.U. achat", "Total"],
        rows=rows, col_widths=[18, 210, 50, 40, 80, 80],
        totals=totals, notes=po.notes, warnings=warnings,
    )
    art = store_artifact(db, dest, filename, "purchase_order", po.id, f"unic-po-{po.number.lower()}", user_id)
    po.artifact_id = art.id
    return art


def create_delivery_note(db: Session, *, title: str, quantities: list[dict],
                         customer_id: str | None, project_id: str | None, user_id: str | None,
                         notes: str = "", quote_number: str | None = None,
                         client_name: str | None = None) -> DeliveryNote:
    buyer = db.get(Customer, customer_id) if customer_id else None
    number = linked_number(db, DOC_CODES["dn"], quote_number=quote_number,
                           party_name=buyer.name if buyer else client_name)
    dn = DeliveryNote(
        number=number, customer_id=customer_id, project_id=project_id,
        title=title or f"Bon de livraison {number}", status="draft",
        notes=notes, created_by=user_id,
    )
    db.add(dn)
    db.flush()
    for i, line in enumerate(quantities, start=1):
        db.add(DeliveryNoteItem(
            note_id=dn.id, position=i,
            description=line.get("name") or line.get("description") or "",
            quantity=float(line.get("quantity") or 0),
            unit=line.get("unit") or "u",
        ))
    generate_dn_pdf(db, dn, user_id)
    audit(db, user_id, "create_dn", "delivery_note", dn.id, dn.number)
    db.commit()
    db.refresh(dn)
    return dn


def generate_dn_pdf(db: Session, dn: DeliveryNote, user_id: str | None) -> Artifact:
    db.flush()
    db.expire(dn, ["items"])   # les lignes ajoutées à l'instant doivent figurer sur le PDF
    company = company_dict(db)
    customer = db.get(Customer, dn.customer_id) if dn.customer_id else None
    items = sorted(dn.items, key=lambda x: x.position)
    rows = [[str(it.position), it.description, fr_num(it.quantity, 2), it.unit] for it in items]
    filename = f"UniC_BL_{dn.number.replace('-', '_')}.pdf"
    dest = settings.artifacts_path / "deliveries" / filename
    build_document_pdf(
        dest, company=company, doc_label="BON DE LIVRAISON", number=dn.number,
        title=dn.title, status=dn.status,
        meta_lines=[f"N° {dn.number}", f"Date {dn.created_at.strftime('%d/%m/%Y') if dn.created_at else ''}"],
        party_left=("Expéditeur", party_text_from_company(company)),
        party_right=("Destinataire", party_text_customer(customer)),
        headers=["#", "Désignation", "Qté", "Unité"],
        rows=rows, col_widths=[24, 340, 70, 70],
        notes=dn.notes,
        extra_paragraphs=["Réception des matériaux : date et signature du destinataire dans le cadre ci-dessous."],
    )
    art = store_artifact(db, dest, filename, "delivery_note", dn.id, f"unic-dn-{dn.number.lower()}", user_id)
    dn.artifact_id = art.id
    return art


def generate_site_report_pdf(db: Session, *, title: str, body_lines: list[str],
                             project_name: str, user_id: str | None, photos_note: str = "") -> Artifact:
    company = company_dict(db)
    number = next_number(db, "report")
    filename = f"UniC_Rapport_{number.replace('-', '_')}.pdf"
    dest = settings.artifacts_path / "reports" / filename
    rows = [[str(i), line, ""] for i, line in enumerate(body_lines, start=1)] or [["—", "Aucun point saisi.", ""]]
    extra = []
    if photos_note:
        extra.append(photos_note)
    extra.append("Les observations visuelles ne constituent pas un diagnostic structurel ou de sécurité.")
    build_document_pdf(
        dest, company=company, doc_label="RAPPORT DE CHANTIER", number=number,
        title=title or f"Rapport {number}", status="draft",
        meta_lines=[f"N° {number}", datetime.now().strftime("%d/%m/%Y")],
        party_left=("Rédacteur", party_text_from_company(company)),
        party_right=("Chantier", project_name or "Chantier non renseigné"),
        headers=["#", "Observation", ""],
        rows=rows, col_widths=[24, 410, 0.1],
        extra_paragraphs=extra,
    )
    art = store_artifact(db, dest, filename, "site_report", number, f"unic-report-{number.lower()}", user_id)
    db.commit()
    return art


def apply_payment(db: Session, invoice: Invoice, amount: float, method: str, reference: str, user_id: str | None) -> Payment:
    if amount <= 0:
        raise ValueError("Montant invalide")
    pay = Payment(invoice_id=invoice.id, amount=amount, method=method, reference=reference, created_by=user_id)
    db.add(pay)
    invoice.paid = round((invoice.paid or 0) + amount, 2)
    if invoice.total is not None:
        invoice.remaining = round(invoice.total - invoice.paid, 2)
        if invoice.remaining <= 0:
            invoice.status = "paid"
            invoice.remaining = 0
        else:
            invoice.status = "partial"
    audit(db, user_id, "payment", "invoice", invoice.id, f"{amount} {method}")
    db.commit()
    db.refresh(invoice)
    return pay


def approve_entity(db, entity, user_id: str) -> None:
    entity.status = "approved"
    entity.approved_by = user_id
    entity.approved_at = utcnow()
    if isinstance(entity, Invoice) and entity.due_date is None:   # échéance : approbation + délai de l'entreprise
        from datetime import timedelta
        entity.due_date = entity.approved_at + timedelta(days=int(company_dict(db).get("invoice_due_days") or 15))
