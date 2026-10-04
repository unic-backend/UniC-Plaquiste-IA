from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import object_session, Session

from app.capabilities import health_dashboard, registry_snapshot
from app.config import settings
from app.database import get_db
from app.documents import process_file, save_upload, search_pages
from app.models import (
    Artifact,
    AuditLog,
    CompanySettings,
    ConstructionSite,
    Conversation,
    Customer,
    DeliveryNote,
    EmailDraft,
    Invoice,
    KnowledgeArticle,
    Material,
    MaterialPrice,
    Message,
    Project,
    PurchaseOrder,
    Quotation,
    Service,
    StoredFile,
    Supplier,
    Task,
    User,
    utcnow,
)
from app import pricecheck
from app.orchestrator import handle_turn
from app.security import get_current_user, require_roles
from app.services import (
    client_name_of,
    apply_payment,
    approve_entity,
    audit,
    company_dict,
    create_delivery_note,
    create_purchase_order,
    generate_dn_pdf,
    generate_invoice_pdf,
    generate_po_pdf,
    generate_quote_pdf,
    invoice_from_quote,
    client_initials,
    document_number,
    next_number,
    quotation_from_quantities,
)
from app.models import InvoiceItem, Payment, QuotationItem

router = APIRouter()


# ---------- auth ----------

class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role)


# ---------- conversations / chat ----------

class ChatIn(BaseModel):
    message: str = ""
    conversation_id: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    deep: bool = False  # raisonnement profond (Claude) à la demande


@router.get("/conversations")
def list_conversations(
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Conversation).filter(Conversation.user_id == user.id)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    rows = query.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(80).all()
    return [
        {"id": c.id, "title": c.title, "pinned": bool(c.pinned),
         "updated_at": c.updated_at.isoformat() if c.updated_at else None}
        for c in rows
    ]


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    pinned: bool | None = None


@router.patch("/conversations/{cid}")
def patch_conversation(cid: str, body: ConversationPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Épingler / renommer : l'ordre par date de dernière activité n'est pas touché."""
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Conversation introuvable")
    if body.title is not None:
        title = " ".join(body.title.split())
        if not title:
            raise HTTPException(422, "Le nom ne peut pas être vide")
        c.title = title
    if body.pinned is not None:
        c.pinned = body.pinned
    db.commit()
    return {"id": c.id, "title": c.title, "pinned": bool(c.pinned)}


@router.post("/conversations")
def new_conversation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = Conversation(user_id=user.id, title="Nouvelle conversation")
    db.add(c)
    db.commit()
    return {"id": c.id, "title": c.title}


@router.get("/conversations/{cid}")
def get_conversation(cid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Conversation introuvable")
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == c.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return {
        "id": c.id,
        "title": c.title,
        "project_id": c.project_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "meta": json.loads(m.meta_json or "{}"),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Conversation introuvable")
    db.delete(c)
    db.commit()
    return {"ok": True}


def _chat_turn(db: Session, user: User, body: ChatIn) -> dict:
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "Conversation introuvable")
    else:
        conv = Conversation(user_id=user.id, title="Nouvelle conversation", project_id=body.project_id)
        db.add(conv)
        db.flush()
    text = (body.message or "").strip()
    if not text and not body.file_ids:
        raise HTTPException(400, "Message vide")
    user_msg = Message(conversation_id=conv.id, role="user", content=text or "[fichier]")
    db.add(user_msg)
    db.flush()
    if conv.title == "Nouvelle conversation" and text:
        conv.title = text[:80]
    reply = handle_turn(db, conv, user, text or "Analyse le fichier.", body.file_ids, body.deep)
    meta = {
        "structured": reply.structured,
        "artifacts": reply.artifacts,
        "capabilities": reply.capabilities,
    }
    asst = Message(
        conversation_id=conv.id, role="assistant", content=reply.content,
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(asst)
    conv.updated_at = utcnow()
    db.commit()
    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "message": {
            "id": asst.id,
            "role": "assistant",
            "content": reply.content,
            "meta": meta,
        },
    }


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _chat_turn(db, user, body)


@router.post("/chat/stream")
def chat_stream(body: ChatIn, user: User = Depends(get_current_user)):
    """Même réponse que /chat, mais en flux (une ligne JSON par événement) : statut, texte au fil de l'eau, puis « done »."""
    import logging
    import queue
    import threading

    from fastapi.responses import StreamingResponse

    from app import ai
    from app.database import SessionLocal

    q: queue.Queue = queue.Queue()
    uid = user.id

    def worker():
        db = SessionLocal()
        tok = ai.STREAM_SINK.set(q.put)
        try:
            q.put({"t": "status", "text": "Je réfléchis…"})
            q.put({"t": "done", **_chat_turn(db, db.get(User, uid), body)})
        except HTTPException as exc:
            q.put({"t": "error", "message": str(exc.detail)})
        except Exception:
            logging.getLogger("unic.chat").exception("chat stream")
            q.put({"t": "error", "message": "Erreur interne. Réessaie dans un instant."})
        finally:
            ai.STREAM_SINK.reset(tok)
            db.close()
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            try:
                ev = q.get(timeout=10)
            except queue.Empty:
                yield "\n"  # signal de vie : garde la connexion ouverte pendant les longues recherches
                continue
            if ev is None:
                return
            yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- files ----------

@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = await file.read()
    max_b = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_b:
        raise HTTPException(413, f"Fichier trop volumineux (max {settings.max_upload_mb} Mo)")
    rec = save_upload(data, file.filename or "fichier", file.content_type or "", user.id, project_id, db)
    info = process_file(rec, db)
    audit(db, user.id, "upload", "file", rec.id, rec.filename)
    db.commit()
    return {
        "id": rec.id,
        "filename": rec.filename,
        "mime_type": rec.mime_type,
        "size": rec.size,
        "processing": info,
    }


@router.get("/files")
def list_files(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(StoredFile).order_by(StoredFile.created_at.desc()).limit(100).all()
    return [
        {
            "id": f.id, "filename": f.filename, "mime_type": f.mime_type, "size": f.size,
            "page_count": f.page_count, "processing_status": f.processing_status,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in rows
    ]


@router.get("/files/{fid}/search")
def file_search(fid: str, q: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rec = db.get(StoredFile, fid)
    if rec is None:
        raise HTTPException(404, "Fichier introuvable")
    return {"hits": search_pages(db, fid, q)}


@router.get("/artifacts/{aid}/download")
def download_artifact(aid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Artifact, aid)
    if a is None:
        raise HTTPException(404, "Document introuvable")
    path = Path(a.path)
    if not path.exists():
        raise HTTPException(404, "Fichier absent du stockage")
    return FileResponse(path, media_type=a.mime_type, filename=a.filename)


@router.get("/artifacts/{aid}/preview")
def preview_artifact(aid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Aperçu du PDF avant téléchargement : une image par page (6 pages au plus)."""
    import base64
    import io

    a = db.get(Artifact, aid)
    if a is None or not Path(a.path).exists():
        raise HTTPException(404, "Document introuvable")
    if a.mime_type != "application/pdf":
        raise HTTPException(415, "Aperçu disponible pour les PDF seulement")
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(a.path))
        images = []
        for i in range(min(len(pdf), 6)):
            buf = io.BytesIO()
            pdf[i].render(scale=1.6).to_pil().convert("RGB").save(buf, format="JPEG", quality=82)
            images.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
        return {"pages": len(pdf), "images": images, "filename": a.filename, "version": a.version}
    except Exception as exc:   # aperçu impossible : le téléchargement reste disponible
        raise HTTPException(503, f"Aperçu indisponible ({type(exc).__name__}). Utilisez Télécharger.")


@router.get("/files/{fid}/download")
def download_file(fid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.get(StoredFile, fid)
    if f is None:
        raise HTTPException(404, "Fichier introuvable")
    path = Path(f.path)
    if not path.exists():
        raise HTTPException(404, "Fichier absent du stockage")
    return FileResponse(path, media_type=f.mime_type, filename=f.filename)


# ---------- CRUD helpers ----------

def _paginate(q, limit: int = 100):
    return q.limit(min(limit, 200)).all()


class CustomerIn(BaseModel):
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    notes: str = ""


@router.get("/customers")
def customers(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Customer)
    if q:
        query = query.filter(or_(Customer.name.ilike(f"%{q}%"), Customer.code.ilike(f"%{q}%")))
    rows = query.order_by(Customer.name).all()
    return [_customer(c) for c in rows]


@router.post("/customers")
def create_customer(body: CustomerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = Customer(code=next_number(db, "customer"), **body.model_dump(), created_by=user.id)
    db.add(c)
    audit(db, user.id, "create", "customer", c.id, c.name)
    db.commit()
    return _customer(c)


@router.get("/customers/{cid}")
def get_customer(cid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Client introuvable")
    return _customer(c)


@router.put("/customers/{cid}")
def update_customer(cid: str, body: CustomerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Client introuvable")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return _customer(c)


def _customer(c: Customer) -> dict:
    return {
        "id": c.id, "code": c.code, "name": c.name, "contact_name": c.contact_name,
        "email": c.email, "phone": c.phone, "address": c.address, "city": c.city, "notes": c.notes,
    }


class SupplierIn(BaseModel):
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    notes: str = ""


@router.get("/suppliers")
def suppliers(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Supplier)
    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))
    return [_supplier(s) for s in query.order_by(Supplier.name).all()]


@router.post("/suppliers")
def create_supplier(body: SupplierIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = Supplier(code=next_number(db, "supplier"), **body.model_dump())
    db.add(s)
    db.commit()
    return _supplier(s)


@router.put("/suppliers/{sid}")
def update_supplier(sid: str, body: SupplierIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Fournisseur introuvable")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return _supplier(s)


def _supplier(s: Supplier) -> dict:
    return {
        "id": s.id, "code": s.code, "name": s.name, "contact_name": s.contact_name,
        "email": s.email, "phone": s.phone, "address": s.address, "notes": s.notes,
    }


class MaterialIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    waste_coefficient: float = 0.08
    notes: str = ""
    availability: str = "unknown"


class PriceIn(BaseModel):
    kind: str
    amount: float
    currency: str = ""
    notes: str = ""


@router.get("/materials")
def materials(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Material).order_by(Material.category, Material.name).all()
    out = []
    for m in rows:
        sell = None
        buy = None
        for p in m.prices:
            if p.kind == "selling" and (sell is None or p.valid_from > sell.valid_from):
                sell = p
            if p.kind == "purchase" and (buy is None or p.valid_from > buy.valid_from):
                buy = p
        out.append({
            "id": m.id, "sku": m.sku, "name": m.name, "category": m.category, "unit": m.unit,
            "waste_coefficient": m.waste_coefficient, "availability": m.availability, "notes": m.notes,
            "selling_price": sell.amount if sell else None,
            "purchase_price": buy.amount if buy else None,
        })
    return out


@router.post("/materials")
def create_material(body: MaterialIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(Material).filter(Material.sku == body.sku).first():
        raise HTTPException(400, "SKU déjà utilisé")
    m = Material(**body.model_dump())
    db.add(m)
    db.commit()
    return {"id": m.id, "sku": m.sku}


@router.post("/materials/{mid}/prices")
def add_price(mid: str, body: PriceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Material, mid)
    if not m:
        raise HTTPException(404, "Matériau introuvable")
    if body.kind not in ("purchase", "selling"):
        raise HTTPException(400, "kind = purchase | selling")
    p = MaterialPrice(material_id=m.id, kind=body.kind, amount=body.amount,
                      currency=body.currency, notes=body.notes, created_by=user.id)
    db.add(p)
    audit(db, user.id, "price", "material", m.id, f"{body.kind}={body.amount}")
    db.commit()
    return {"id": p.id}


@router.get("/services")
def services(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Service).all()
    return [
        {
            "id": s.id, "code": s.code, "name": s.name, "description": s.description, "unit": s.unit,
            "selling_price": s.selling_price, "labor_rate": s.labor_rate, "notes": s.notes,
        }
        for s in rows
    ]


class ProjectIn(BaseModel):
    name: str
    customer_id: str | None = None
    location: str = ""
    description: str = ""
    budget: float | None = None
    notes: str = ""
    status: str = "active"


@router.get("/projects")
def projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Project).order_by(Project.created_at.desc()).all()
    return [_project(p) for p in rows]


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = Project(code=next_number(db, "project"), created_by=user.id, **body.model_dump())
    db.add(p)
    db.flush()
    db.add(ConstructionSite(project_id=p.id, name=p.name, location=p.location, status="planned"))
    db.commit()
    db.refresh(p)
    return _project(p)


@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    sites = db.query(ConstructionSite).filter(ConstructionSite.project_id == p.id).all()
    quotes = db.query(Quotation).filter(Quotation.project_id == p.id).all()
    invs = db.query(Invoice).filter(Invoice.project_id == p.id).all()
    data = _project(p)
    data["sites"] = [
        {
            "id": s.id, "name": s.name, "status": s.status, "progress_pct": s.progress_pct,
            "location": s.location, "notes": s.notes,
            "tasks": [{"id": t.id, "title": t.title, "status": t.status} for t in s.tasks],
        }
        for s in sites
    ]
    data["quotations"] = [{"id": q.id, "number": q.number, "status": q.status, "total": q.total} for q in quotes]
    data["invoices"] = [{"id": i.id, "number": i.number, "status": i.status, "total": i.total, "paid": i.paid} for i in invs]
    return data


class TaskIn(BaseModel):
    title: str
    notes: str = ""


@router.post("/projects/{pid}/tasks")
def add_task(pid: str, body: TaskIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    site = db.query(ConstructionSite).filter(ConstructionSite.project_id == pid).first()
    if not site:
        site = ConstructionSite(project_id=pid, name=p.name)
        db.add(site)
        db.flush()
    t = Task(site_id=site.id, title=body.title, notes=body.notes)
    db.add(t)
    db.commit()
    return {"id": t.id}


def _project(p: Project) -> dict:
    return {
        "id": p.id, "code": p.code, "name": p.name, "status": p.status, "location": p.location,
        "description": p.description, "budget": p.budget, "notes": p.notes,
        "customer_id": p.customer_id,
        "customer_name": p.customer.name if p.customer else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ---------- documents métier ----------

def _quote_out(q: Quotation) -> dict:
    return {
        "id": q.id, "number": q.number, "title": q.title, "object_text": q.object_text, "site_location": q.site_location, "client_name": _client_of(q), "status": q.status,
        "customer_id": q.customer_id, "customer_name": q.customer.name if q.customer else None,
        "client_label": q.client_label,
        "project_id": q.project_id, "currency": q.currency,
        "subtotal": q.subtotal, "vat_rate": q.vat_rate, "vat_amount": q.vat_amount,
        "total": q.total, "prices_complete": q.prices_complete,
        "notes": q.notes, "assumptions": q.assumptions, "missing_info": q.missing_info,
        "artifact_id": q.artifact_id, "version": q.version,
        "price_check": pricecheck.check_quote(q),
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "items": [
            {
                "id": it.id, "position": it.position, "description": it.description,
                "quantity": it.quantity, "unit": it.unit, "unit_price": it.unit_price,
                "total": it.total, "data_status": it.data_status, "formula": it.formula,
            }
            for it in sorted(q.items, key=lambda x: x.position)
        ],
    }


@router.get("/quotes")
def quotes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Quotation).order_by(Quotation.created_at.desc()).all()
    return [_quote_out(q) for q in rows]


@router.get("/quotes/{qid}")
def get_quote(qid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    data = _quote_out(q)
    if q.artifact_id:
        a = db.get(Artifact, q.artifact_id)
        if a:
            data["download_url"] = f"/api/artifacts/{a.id}/download"
            data["filename"] = a.filename
    return data


class QuotePatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    customer_id: str | None = None
    items: list[dict] | None = None


@router.patch("/quotes/{qid}")
def patch_quote(qid: str, body: QuotePatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    if q.status == "approved" and user.role != "admin":
        raise HTTPException(400, "Devis approuvé : modification réservée à l'admin")
    if body.title is not None:
        q.title = body.title
    if body.notes is not None:
        q.notes = body.notes
    if body.customer_id is not None:
        q.customer_id = body.customer_id
        owner = db.get(Customer, body.customer_id)
        if owner is not None and q.status == "draft":
            # le numéro porte les initiales du client : il suit le client tant que le devis est un brouillon
            current = document_number(db, owner.name, q.created_at.date() if q.created_at else None)
            if not q.number.startswith(current.rsplit("-", 1)[0] + "-" + client_initials(owner.name)):
                q.number = current
            q.client_label = ""
    if body.items is not None:
        db.query(QuotationItem).filter(QuotationItem.quotation_id == q.id).delete()
        subtotal = 0.0
        complete = True
        any_price = False
        for i, it in enumerate(body.items, start=1):
            qty = float(it.get("quantity") or 0)
            up = it.get("unit_price")
            total = None
            if up is None:
                complete = False
            else:
                up = float(up)
                total = round(qty * up, 2)
                subtotal += total
                any_price = True
            db.add(QuotationItem(
                quotation_id=q.id, position=i,
                description=it.get("description") or "",
                quantity=qty, unit=it.get("unit") or "u",
                unit_price=up if up is not None else None, total=total,
                data_status=it.get("data_status") or "confirmed",
                formula=it.get("formula") or "",
            ))
        q.prices_complete = complete and any_price
        q.subtotal = round(subtotal, 2) if any_price else None
        if q.subtotal is not None and q.vat_rate is not None:
            q.vat_amount = round(q.subtotal * q.vat_rate, 2)
            q.total = round(q.subtotal + q.vat_amount, 2)
        else:
            q.total = q.subtotal
        q.version += 1
    q.updated_at = utcnow()
    generate_quote_pdf(db, q, user.id)
    db.commit()
    db.refresh(q)
    return _quote_out(q)


@router.post("/quotes/{qid}/approve")
def approve_quote(qid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    approve_entity(db, q, user.id)
    generate_quote_pdf(db, q, user.id)
    db.commit()
    return {"status": q.status, "number": q.number}


@router.post("/quotes/{qid}/invoice")
def quote_to_invoice(qid: str, kind: str = "invoice", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    inv = invoice_from_quote(db, q, kind, user.id)
    return {"id": inv.id, "number": inv.number}


@router.get("/invoices")
def invoices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Invoice).order_by(Invoice.created_at.desc()).all()
    return [_invoice(i) for i in rows]


@router.get("/invoices/{iid}")
def get_invoice(iid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(Invoice, iid)
    if not i:
        raise HTTPException(404, "Facture introuvable")
    data = _invoice(i)
    if i.artifact_id:
        data["download_url"] = f"/api/artifacts/{i.artifact_id}/download"
    return data


class PaymentIn(BaseModel):
    amount: float
    method: str = ""
    reference: str = ""


@router.post("/invoices/{iid}/payments")
def pay_invoice(iid: str, body: PaymentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(Invoice, iid)
    if not i:
        raise HTTPException(404, "Facture introuvable")
    apply_payment(db, i, body.amount, body.method, body.reference, user.id)
    generate_invoice_pdf(db, i, user.id)
    db.commit()
    return _invoice(i)


@router.post("/invoices/{iid}/approve")
def approve_invoice(iid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(Invoice, iid)
    if not i:
        raise HTTPException(404)
    approve_entity(db, i, user.id)
    generate_invoice_pdf(db, i, user.id)
    db.commit()
    return {"status": i.status}


def _client_of(doc) -> str:
    db = object_session(doc)
    return client_name_of(db, doc) if db is not None else ""


def _invoice(i: Invoice) -> dict:
    return {
        "id": i.id, "number": i.number, "kind": i.kind, "title": i.title, "status": i.status,
        "customer_name": i.customer.name if i.customer else None,
        "client_name": _client_of(i),
        "subtotal": i.subtotal, "vat_amount": i.vat_amount, "total": i.total,
        "paid": i.paid, "remaining": i.remaining, "currency": i.currency,
        "artifact_id": i.artifact_id,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "items": [
            {
                "position": it.position, "description": it.description, "quantity": it.quantity,
                "unit": it.unit, "unit_price": it.unit_price, "total": it.total,
            }
            for it in sorted(i.items, key=lambda x: x.position)
        ],
        "payments": [
            {"id": p.id, "amount": p.amount, "method": p.method, "reference": p.reference,
             "paid_at": p.paid_at.isoformat() if p.paid_at else None}
            for p in i.payments
        ],
    }


@router.get("/purchase-orders")
def pos(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).all()
    return [_po(p) for p in rows]


@router.get("/purchase-orders/{oid}")
def get_po(oid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(PurchaseOrder, oid)
    if not p:
        raise HTTPException(404)
    data = _po(p)
    if p.artifact_id:
        data["download_url"] = f"/api/artifacts/{p.artifact_id}/download"
    return data


@router.post("/purchase-orders/{oid}/approve")
def approve_po(oid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(PurchaseOrder, oid)
    if not p:
        raise HTTPException(404)
    approve_entity(db, p, user.id)
    generate_po_pdf(db, p, user.id)
    db.commit()
    return {"status": p.status}


def _po(p: PurchaseOrder) -> dict:
    return {
        "id": p.id, "number": p.number, "title": p.title, "status": p.status, "total": p.total,
        "supplier_name": p.supplier.name if p.supplier else None, "client_name": _client_of(p), "artifact_id": p.artifact_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "items": [
            {"position": it.position, "description": it.description, "quantity": it.quantity,
             "unit": it.unit, "unit_price": it.unit_price, "total": it.total}
            for it in sorted(p.items, key=lambda x: x.position)
        ],
    }


@router.get("/delivery-notes")
def dns(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(DeliveryNote).order_by(DeliveryNote.created_at.desc()).all()
    return [_dn(n) for n in rows]


@router.get("/delivery-notes/{nid}")
def get_dn(nid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.get(DeliveryNote, nid)
    if not n:
        raise HTTPException(404)
    data = _dn(n)
    if n.artifact_id:
        data["download_url"] = f"/api/artifacts/{n.artifact_id}/download"
    return data


def _dn(n: DeliveryNote) -> dict:
    return {
        "id": n.id, "number": n.number, "title": n.title, "status": n.status,
        "customer_name": n.customer.name if n.customer else None, "client_name": _client_of(n), "artifact_id": n.artifact_id,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "items": [
            {"position": it.position, "description": it.description, "quantity": it.quantity, "unit": it.unit}
            for it in sorted(n.items, key=lambda x: x.position)
        ],
    }


# ---------- knowledge / settings / health ----------

@router.get("/knowledge")
def knowledge(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(KnowledgeArticle).all()
    if q:
        ql = q.lower()
        rows = [a for a in rows if ql in (a.title + a.body).lower()]
    return [{"id": a.id, "slug": a.slug, "title": a.title, "category": a.category, "body": a.body} for a in rows]


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return company_dict(db)


class SettingsIn(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    tax_id: str | None = None
    currency: str | None = None
    vat_rate: float | None = None
    quote_validity_days: int | None = None
    payment_terms: str | None = None
    default_waste: float | None = None
    default_margin: float | None = None
    board_width_m: float | None = None
    board_height_m: float | None = None
    stud_spacing_m: float | None = None
    notes: str | None = None


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager"))):
    row = db.query(CompanySettings).first()
    if row is None:
        row = CompanySettings()
        db.add(row)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updated_at = utcnow()
    audit(db, user.id, "update", "settings", row.id)
    db.commit()
    return company_dict(db)


@router.get("/health")
def health():
    return health_dashboard()


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    return registry_snapshot()


@router.get("/audit")
def audit_list(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return [
        {
            "id": a.id, "user_id": a.user_id, "action": a.action, "entity_type": a.entity_type,
            "entity_id": a.entity_id, "details": a.details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.get("/emails")
def email_drafts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(EmailDraft).order_by(EmailDraft.created_at.desc()).limit(50).all()
    return [
        {
            "id": e.id, "to": e.to_addr, "subject": e.subject, "body": e.body,
            "status": e.status, "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.get("/search")
def global_search(q: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    qn = f"%{q}%"
    return {
        "customers": [_customer(c) for c in db.query(Customer).filter(Customer.name.ilike(qn)).limit(8)],
        "projects": [_project(p) for p in db.query(Project).filter(Project.name.ilike(qn)).limit(8)],
        "quotes": [{"id": x.id, "number": x.number, "title": x.title} for x in db.query(Quotation).filter(or_(Quotation.number.ilike(qn), Quotation.title.ilike(qn))).limit(8)],
        "invoices": [{"id": x.id, "number": x.number} for x in db.query(Invoice).filter(Invoice.number.ilike(qn)).limit(8)],
        "materials": [{"id": m.id, "sku": m.sku, "name": m.name} for m in db.query(Material).filter(or_(Material.name.ilike(qn), Material.sku.ilike(qn))).limit(8)],
        "knowledge": [{"id": a.id, "title": a.title, "slug": a.slug} for a in db.query(KnowledgeArticle).all() if q.lower() in (a.title + a.body).lower()][:8],
    }


class CalcIn(BaseModel):
    text: str | None = None
    kind: str | None = None
    length_m: float | None = None
    height_m: float | None = None
    width_m: float | None = None
    sides: int = 2
    area_m2: float | None = None


@router.post("/calc")
def calc_api(body: CalcIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import calc as calcmod
    company = company_dict(db)
    defaults = {
        "waste": company.get("default_waste") or 0.08,
        "board_width_m": company.get("board_width_m") or 1.2,
        "board_height_m": company.get("board_height_m") or 2.5,
        "stud_spacing_m": company.get("stud_spacing_m") or 0.6,
    }
    if body.text:
        r = calcmod.calculate_from_text(body.text, defaults)
        if r is None:
            raise HTTPException(400, "Calcul non interprété")
        return r.to_dict()
    if body.kind == "partition" and body.length_m and body.height_m:
        return calcmod.calculate_partition(body.length_m, body.height_m, body.sides, waste=defaults["waste"]).to_dict()
    if body.kind == "ceiling" and body.length_m and body.width_m:
        return calcmod.calculate_ceiling(body.length_m, body.width_m, waste=defaults["waste"]).to_dict()
    raise HTTPException(400, "Paramètres insuffisants")
