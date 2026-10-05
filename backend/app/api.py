from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, object_session, selectinload

from app import learned
from app.capabilities import _connectors, health_dashboard, registry_snapshot, release_memory
from app.config import settings
from app.database import SLOW_QUERIES, get_db
from app.documents import UploadRejected, process_file, save_upload, search_pages
from app.models import (
    LearnedAnswer,
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
from app.cover import ensure_cover_letter, make_cover_letter
from app.orchestrator import handle_turn
from app.security import get_current_user, require_roles
from app.services import (
    client_name_of,
    apply_payment,
    approve_entity,
    balance_message,
    build_balance_pdf,
    reliquat_data,
    audit,
    company_dict,
    generate_invoice_pdf,
    generate_po_pdf,
    generate_quote_pdf,
    invoice_from_quote,
    client_initials,
    document_number,
    next_number,
)
from app.models import QuotationItem

router = APIRouter()


# ---------- auth ----------

class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    device: str = Field(default="", max_length=120)


class AccountIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    current_password: str = Field(default="", max_length=200)


_login_fails: dict[str, list[float]] = {}


@router.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    from app import auth
    return {"account": auth.account_ready(db), "code_required": bool(settings.unic_access_code)}


@router.post("/auth/login")
def auth_login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    import time as _time
    from app import auth
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    recent = [t for t in _login_fails.get(ip, []) if _time.time() - t < 900]
    if len(recent) >= 8:
        raise HTTPException(429, "Trop d'essais. Réessaie dans 15 minutes.")
    try:
        token = auth.login(db, body.email, body.password, body.device)
    except auth.AuthError as exc:
        _login_fails[ip] = recent + [_time.time()]
        raise HTTPException(401, str(exc))
    _login_fails.pop(ip, None)
    db.commit()
    return {"token": token}


@router.post("/auth/logout")
def auth_logout(request: Request, db: Session = Depends(get_db)):
    from app import auth
    auth.logout(db, request.headers.get("x-access-code", ""))
    db.commit()
    return {"ok": True}


@router.put("/auth/account")
def auth_account(body: AccountIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Choisir / changer son e-mail et son mot de passe. Avec le code d'accès (mot de passe oublié), l'ancien n'est pas demandé."""
    import secrets as _secrets
    from app import auth
    given = request.headers.get("x-access-code", "")
    code = settings.unic_access_code
    by_code = bool(code) and _secrets.compare_digest(given.encode(), code.encode())
    if not code:
        by_code = not given.startswith("uat_")
    try:
        auth.set_account(db, body.email, body.password, body.current_password, by_access_code=by_code)
        token = auth.login(db, body.email, body.password, "Cet appareil")
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"ok": True, "token": token}


@router.get("/auth/devices")
def auth_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import auth
    return {"devices": auth.devices(db), "account": auth.account_ready(db), "email": user.email if auth.account_ready(db) else ""}


@router.get("/auth/me")
def me(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app import auth
    try:
        auth.touch(db, request.headers.get("x-access-code", ""))
        db.commit()
    except Exception:
        db.rollback()
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
    ok_ids = learned.validated_ids(db, [m.id for m in msgs if m.role == "assistant"])
    return {
        "id": c.id,
        "title": c.title,
        "project_id": c.project_id,
        "working": c.id in RUNNING,   # UniC travaille encore sur la dernière demande
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "validated": m.id in ok_ids,
                "meta": json.loads(m.meta_json or "{}"),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.post("/messages/{mid}/validate")
def validate_message(mid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """👍 : la réponse devient du savoir validé, réutilisable quand Claude est indisponible."""
    try:
        learned.validate(db, mid)
    except learned.LearnError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"validated": True, "total": db.query(LearnedAnswer).count()}


@router.delete("/messages/{mid}/validate")
def unvalidate_message(mid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    learned.forget(db, mid)
    db.commit()
    return {"validated": False, "total": db.query(LearnedAnswer).count()}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Conversation introuvable")
    db.delete(c)
    db.commit()
    return {"ok": True}


# Conversations dont la réponse est en cours : le travail continue sur le serveur même si l'appli est quittée.
RUNNING: set[str] = set()


def _chat_turn(db: Session, user: User, body: ChatIn, on_start=None) -> dict:
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
    names = [{"id": f.id, "filename": f.filename, "mime": f.mime_type} for f in (db.get(StoredFile, i) for i in body.file_ids) if f is not None]
    user_msg = Message(conversation_id=conv.id, role="user", content=text or "[fichier]",
                       meta_json=json.dumps({"files": names}, ensure_ascii=False) if names else "{}")
    db.add(user_msg)
    db.flush()
    if conv.title == "Nouvelle conversation" and text:
        conv.title = text[:80]
    db.commit()   # la demande est enregistrée tout de suite : retrouvable même si l'appli est fermée pendant le travail
    if on_start:
        on_start(conv.id)
    RUNNING.add(conv.id)
    try:
        reply = handle_turn(db, conv, user, text or "Analyse le fichier.", body.file_ids, body.deep)
    except HTTPException:
        raise
    except Exception:
        db.rollback()   # la demande reste ; une réponse claire remplace le silence
        db.add(Message(conversation_id=conv.id, role="assistant",
                       content="Je n'ai pas pu terminer cette tâche (erreur interne). Redemande-la et je la reprends.", meta_json="{}"))
        db.commit()
        raise
    finally:
        RUNNING.discard(conv.id)
        release_memory()
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
def chat(body: ChatIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import memory as mem

    pending: list[str] = []
    tok = mem.AFTER_REPLY.set(pending)
    try:
        out = _chat_turn(db, user, body)
    finally:
        mem.AFTER_REPLY.reset(tok)
    for t in pending:
        background.add_task(mem.extract_in_background, t)   # après l'envoi de la réponse
    return out


@router.post("/chat/stream")
def chat_stream(body: ChatIn, user: User = Depends(get_current_user)):
    """Même réponse que /chat, mais en flux (une ligne JSON par événement) : statut, texte au fil de l'eau, puis « done »."""
    import logging
    import queue
    import threading

    from fastapi.responses import StreamingResponse

    from app import ai
    from app.database import SessionLocal

    from app import memory as mem

    q: queue.Queue = queue.Queue()
    uid = user.id
    pending: list[str] = []

    def worker():
        db = SessionLocal()
        tok = ai.STREAM_SINK.set(q.put)
        mtok = mem.AFTER_REPLY.set(pending)
        try:
            q.put({"t": "status", "text": "Je réfléchis…"})
            q.put({"t": "done", **_chat_turn(db, db.get(User, uid), body,
                                             on_start=lambda cid: q.put({"t": "conv", "conversation_id": cid}))})
            q.put(None)   # flux fermé : l'écran n'attend plus
            for t in pending:
                mem.extract_in_background(t)   # la mémoire se met à jour ensuite
        except HTTPException as exc:
            q.put({"t": "error", "message": str(exc.detail)})
        except Exception:
            logging.getLogger("unic.chat").exception("chat stream")
            q.put({"t": "error", "message": "Erreur interne. Réessaie dans un instant."})
        finally:
            ai.STREAM_SINK.reset(tok)
            mem.AFTER_REPLY.reset(mtok)
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
    try:
        rec = save_upload(data, file.filename or "fichier", file.content_type or "", user.id, project_id, db)
    except UploadRejected as exc:
        raise HTTPException(415, str(exc))
    info = process_file(rec, db)
    audit(db, user.id, "upload", "file", rec.id, rec.filename)
    db.commit()
    del data
    release_memory()
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


@router.get("/files/{fid}/thumb")
def file_thumb(fid: str, size: int = 600, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Aperçu JPEG d'une photo ou de la 1re page d'un PDF (plan) : affiché en carte dans la conversation. Mis en cache."""
    import base64
    from app import pdfjob

    f = db.get(StoredFile, fid)
    if f is None or not Path(f.path).exists():
        raise HTTPException(404, "Fichier introuvable")
    size = 1600 if size > 600 else 600
    src = Path(f.path)
    thumb = src.with_name(f"{src.stem}.thumb{size}.jpg")
    if not thumb.exists():
        ext = src.suffix.lower()
        try:
            if ext == ".pdf":
                data = pdfjob.run("images", timeout=60, path=str(src), pages=[0], max_side=size, quality=80)["images"]
                if not data:
                    raise ValueError("vide")
                thumb.write_bytes(base64.b64decode(data[0]))
            elif ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                from PIL import Image
                with Image.open(src) as img:
                    im = img.convert("RGB")
                    im.thumbnail((size, size))
                    im.save(thumb, "JPEG", quality=80)
            else:
                raise HTTPException(415, "Pas d'aperçu pour ce type de fichier")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Aperçu impossible")
        finally:
            release_memory()
    return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


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



class Page:
    """Pagination commune : ?limit=&offset= (défaut 500, max 1000). Le total est dans l'en-tête X-Total-Count."""

    def __init__(self, limit: int = Query(500, ge=1, le=1000), offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset

    def apply(self, query, response: Response):
        response.headers["X-Total-Count"] = str(query.count())
        return query.offset(self.offset).limit(self.limit).all()


@router.get("/customers")
def customers(response: Response, page: Page = Depends(), q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Customer)
    if q:
        query = query.filter(or_(Customer.name.ilike(f"%{q}%"), Customer.code.ilike(f"%{q}%")))
    rows = page.apply(query.order_by(Customer.name), response)
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
def projects(response: Response, page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = page.apply(db.query(Project).order_by(Project.created_at.desc()), response)
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
        "id": q.id, "number": q.number, "title": q.title, "cover_letter": q.cover_letter or "", "object_text": q.object_text, "site_location": q.site_location, "client_name": _client_of(q), "status": q.status,
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



@router.get("/export/{kind}.{fmt}")
def export_accounting(kind: str, fmt: str, start: str = "", end: str = "", db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Export comptable (devis ou factures) en CSV ou Excel. Filtre : ?start=AAAA-MM-JJ&end=AAAA-MM-JJ."""
    from datetime import datetime, timezone
    from app import exports
    if kind not in ("quotes", "invoices") or fmt not in ("csv", "xlsx"):
        raise HTTPException(404, "Export inconnu (quotes ou invoices, csv ou xlsx).")
    try:
        d0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else None
        d1 = datetime.fromisoformat(end).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end else None
    except ValueError:
        raise HTTPException(400, "Date invalide : utilise AAAA-MM-JJ.")
    data = exports.rows(db, kind, d0, d1)
    audit(db, user.id, "export", kind, fmt, f"{len(data)} ligne(s)")
    db.commit()
    name = f"unic-{'devis' if kind == 'quotes' else 'factures'}-{datetime.now(timezone.utc).date().isoformat()}.{fmt}"
    if fmt == "csv":
        body, mime = exports.to_csv(data), "text/csv; charset=utf-8"
    else:
        body, mime = exports.to_xlsx(data, "Devis" if kind == "quotes" else "Factures"), \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})

@router.get("/quotes")
def quotes(response: Response, page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = page.apply(db.query(Quotation).options(selectinload(Quotation.items), joinedload(Quotation.customer))
                      .order_by(Quotation.created_at.desc()), response)
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
    ensure_cover_letter(db, q)   # lettre d'accompagnement préparée à l'approbation
    db.commit()
    return {"status": q.status, "number": q.number, "cover_letter": q.cover_letter or ""}


class CoverLetterIn(BaseModel):
    text: str = Field(..., max_length=4000)


@router.post("/quotes/{qid}/cover-letter")
def regenerate_cover_letter(qid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    q.cover_letter = make_cover_letter(db, q)
    audit(db, user.id, "cover_letter", "quotation", q.id)
    db.commit()
    return {"cover_letter": q.cover_letter}


@router.put("/quotes/{qid}/cover-letter")
def edit_cover_letter(qid: str, body: CoverLetterIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    text = body.text.strip()
    if len(text.split()) > 250:
        raise HTTPException(400, "Lettre trop longue : 250 mots au maximum.")
    q.cover_letter = text
    db.commit()
    return {"cover_letter": q.cover_letter}


@router.post("/quotes/{qid}/invoice")
def quote_to_invoice(qid: str, kind: str = "invoice", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    inv = invoice_from_quote(db, q, kind, user.id)
    return {"id": inv.id, "number": inv.number}


@router.get("/invoices")
def invoices(response: Response, page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = page.apply(db.query(Invoice).options(selectinload(Invoice.items), selectinload(Invoice.payments), joinedload(Invoice.customer))
                      .order_by(Invoice.created_at.desc()), response)
    return [_invoice(i) for i in rows]


@router.get("/invoices/{iid}")
def get_invoice(iid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(Invoice, iid)
    if not i:
        raise HTTPException(404, "Facture introuvable")
    data = _invoice(i)
    if i.artifact_id:
        data["download_url"] = f"/api/artifacts/{i.artifact_id}/download"
    if i.status != "draft" and (reliquat_data(db, i)["remaining"] or 0) > 0:   # reliquat : PDF + message de rappel
        co = company_dict(db)
        cust = db.get(Customer, i.customer_id) if i.customer_id else None
        data["balance_url"] = f"/api/invoices/{i.id}/balance"
        data["balance_message"] = balance_message(db, i, (cust.contact_name or cust.name) if cust else "", i.currency or co.get("currency") or "", co.get("phone") or "")
    return data


@router.get("/invoices/{iid}/balance")
def invoice_balance_pdf(iid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.get(Invoice, iid)
    if not i:
        raise HTTPException(404, "Facture introuvable")
    if (reliquat_data(db, i)["remaining"] or 0) <= 0:
        raise HTTPException(409, "Le dossier est entièrement payé : pas de reliquat.")
    path = build_balance_pdf(db, i)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


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
def pos(response: Response, page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = page.apply(db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()), response)
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
def dns(response: Response, page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = page.apply(db.query(DeliveryNote).order_by(DeliveryNote.created_at.desc()), response)
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
    invoice_due_days: int | None = Field(default=None, ge=0, le=365)
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


@router.get("/settings/signature")
def get_signature(user: User = Depends(get_current_user)):
    from app.pdfs import owner_signature_path
    p = owner_signature_path()
    if not p.exists():
        raise HTTPException(404, "Aucune signature enregistrée")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


def _save_brand_image(data: bytes, dest) -> dict:
    from app import inkimage
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Image trop lourde (15 Mo maximum).")
    try:
        ink = inkimage.extract(inkimage.load(data))
    except inkimage.InkError as exc:
        raise HTTPException(400, str(exc))
    dest.parent.mkdir(parents=True, exist_ok=True)
    ink.save(dest, "PNG")
    return {"ok": True, "width": ink.width, "height": ink.height}


@router.put("/settings/signature")
async def put_signature(file: UploadFile = File(...), user: User = Depends(require_roles("admin", "manager")),
                        db: Session = Depends(get_db)):
    """Signature du gérant (photo sur papier blanc) : fond retiré, recadrée, encre bleu foncé, PNG transparent."""
    from app.pdfs import owner_signature_path
    out = _save_brand_image(await file.read(), owner_signature_path())
    audit(db, user.id, "update", "signature", "owner")
    db.commit()
    return out


@router.get("/settings/stamp")
def get_stamp(user: User = Depends(get_current_user)):
    from app.pdfs import owner_stamp_path
    p = owner_stamp_path()
    if not p.exists():
        raise HTTPException(404, "Aucun cachet enregistré")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.put("/settings/stamp")
async def put_stamp(file: UploadFile = File(...), user: User = Depends(require_roles("admin", "manager")),
                    db: Session = Depends(get_db)):
    """Cachet de l'entreprise (photo du tampon sur papier) : posé à côté de la signature sur les documents."""
    from app.pdfs import uploaded_stamp_path
    out = _save_brand_image(await file.read(), uploaded_stamp_path())
    audit(db, user.id, "update", "stamp", "owner")
    db.commit()
    return out


@router.delete("/settings/stamp")
def delete_stamp(user: User = Depends(require_roles("admin", "manager"))):
    from app.pdfs import uploaded_stamp_path
    uploaded_stamp_path().unlink(missing_ok=True)   # le cachet intégré reprend sa place
    return {"ok": True}


@router.delete("/settings/signature")
def delete_signature(user: User = Depends(require_roles("admin", "manager"))):
    from app.pdfs import owner_signature_path
    owner_signature_path().unlink(missing_ok=True)
    return {"ok": True}


class AppointmentIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    start: str
    kind: str = "rdv"
    duration_min: int | None = None
    location: str = ""
    client_name: str = ""
    phone: str = ""
    notes: str = ""
    remind_minutes: int = 60


@router.get("/agenda")
def agenda_list(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import agenda
    return {"rdv": [agenda.to_dict(a) for a in agenda.upcoming(db, days=max(1, min(days, 365)))], "kinds": agenda.KINDS}


@router.post("/agenda")
def agenda_create(body: AppointmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import agenda
    try:
        a, clash = agenda.create(db, **body.model_dump())
    except agenda.AgendaError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"rdv": agenda.to_dict(a), "conflits": [agenda.line(c) for c in clash]}


@router.patch("/agenda/{aid}")
def agenda_update(aid: str, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import agenda
    from app.models import Appointment
    a = db.get(Appointment, aid)
    if a is None:
        raise HTTPException(404, "Rendez-vous introuvable")
    if body.get("status") in ("planned", "done", "cancelled"):
        a.status = body["status"]
    if body.get("start"):
        try:
            s = agenda.parse_dt(body["start"])
        except agenda.AgendaError as exc:
            raise HTTPException(400, str(exc))
        dur = (agenda._aware(a.end_at) - agenda._aware(a.start_at)) if a.end_at else None
        a.start_at = s
        if dur:
            a.end_at = s + dur
    db.commit()
    return {"rdv": agenda.to_dict(a)}


@router.post("/worker/poll")
def worker_poll(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Appelé en boucle par l'appli Windows : signale le PC en ligne et récupère une question à traiter."""
    from app import localworker
    hold = 0.0 if body.get("hold") == 0 else localworker.POLL_HOLD
    return {"job": localworker.next_job(None, str(body.get("model") or "")[:64], hold=hold)}


@router.post("/worker/result/{jid}")
def worker_result(jid: str, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import localworker
    ok = localworker.finish(db, jid, str(body.get("text") or ""), str(body.get("model") or ""), ok=bool(body.get("ok", True)))
    return {"ok": ok}


@router.get("/worker/status")
def worker_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import localworker
    return localworker.status(db)


@router.get("/leads")
def leads_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import sitechat
    return [{"id": l.id, "name": l.name, "phone": l.phone, "area": l.area, "need": l.need, "surface": l.surface,
             "status": l.status, "created_at": l.created_at.isoformat() if l.created_at else None} for l in sitechat.new_leads(db, 90)]


@router.patch("/leads/{lid}")
def leads_update(lid: str, body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import WebLead
    lead = db.get(WebLead, lid)
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    if body.get("status") in ("new", "contacted", "done"):
        lead.status = body["status"]
    db.commit()
    return {"ok": True, "status": lead.status}


@router.get("/invoices-unpaid")
def invoices_unpaid(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app import unpaid
    u = unpaid.unpaid(db)
    company = company_dict(db).get("name") or "UniC Plaquiste"
    for r in u["en_retard"] + u["a_venir"]:
        r["relance"] = unpaid.reminder_text(r, company)
    return u


@router.get("/backups")
def backups_list(user: User = Depends(require_roles("admin", "manager"))):
    from app import backup
    return {"backups": backup.list_local(), "status": backup.status(), "offsite": backup.offsite_available(),
            "folder": backup.REMOTE_FOLDER, "every_hours": backup.EVERY_HOURS}


@router.post("/backups")
def backups_create(user: User = Depends(require_roles("admin", "manager"))):
    from app import backup
    try:
        made = backup.create("manuel")
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc))
    remote = None
    if backup.offsite_available():
        try:
            remote = backup.push_offsite(made["name"])
        except backup.BackupError as exc:
            remote = {"ok": False, "error": str(exc)}
    release_memory()
    return {**made, "offsite": remote}


@router.get("/backups/{name}/download")
def backups_download(name: str, user: User = Depends(require_roles("admin", "manager"))):
    from app import backup
    try:
        p = backup.path_of(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(p, media_type="application/zip", filename=name)


@router.post("/backups/restore")
async def backups_restore(file: UploadFile = File(...), user: User = Depends(require_roles("admin"))):
    from app import backup
    data = await file.read()
    try:
        out = backup.restore(data)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc))
    finally:
        release_memory()
    return out


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return health_dashboard(db)


@router.get("/connectors")
def connectors(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """État réel des connecteurs, pour les raccourcis du chat (rien de figé)."""
    return _connectors(db)


@router.get("/capabilities")
def capabilities(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return registry_snapshot(db)


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
        "board_height_m": company.get("board_height_m") or 2.0,
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


# ---------- Atelier : UniC se surveille, se corrige, crée ses agents ----------

ADMIN = require_roles("admin", "manager")


class RepairIn(BaseModel):
    kind: str = "fix"
    request: str = ""
    incident_id: str = ""


class GithubIn(BaseModel):
    token: str = ""
    repo: str = ""
    base: str = ""
    deploy_hook: str = ""


class AgentIn(BaseModel):
    name: str
    mission: str
    every_hours: int = 24


class StatusIn(BaseModel):
    status: str


def _repair_call(fn, *a):
    from app import repair
    try:
        return fn(*a)
    except repair.RepairError as exc:
        raise HTTPException(exc.status, str(exc))


@router.get("/selfcare")
def selfcare_overview(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import agents, repair, selfcare
    from app.models import AppSetting, CustomAgent, RepairJob
    selfcare.ensure_running()
    last = db.get(AppSetting, "selfcheck_last")
    return {"incidents": selfcare.incidents(db, "open"), "sleeping": selfcare.sleeping(),
            "last_check": last.value if last else None, "github": repair.status(db),
            "slow_queries": list(reversed(SLOW_QUERIES)),
            "jobs": [repair.to_dict(j) for j in db.query(RepairJob).order_by(RepairJob.created_at.desc()).limit(20).all()],
            "agents": [agents.to_dict(a) for a in db.query(CustomAgent).order_by(CustomAgent.created_at.desc()).all()]}


@router.post("/selfcare/check")
def selfcare_check(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import selfcare
    selfcare.wake_sleepers()
    return selfcare.self_check(db)


@router.get("/selfcare/incidents/{iid}")
def selfcare_incident(iid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import selfcare
    from app.models import Incident
    i = db.get(Incident, iid)
    if i is None:
        raise HTTPException(404, "Incident introuvable")
    return selfcare.to_dict(i, detail=True)


@router.patch("/selfcare/incidents/{iid}")
def selfcare_incident_status(iid: str, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import selfcare
    from app.models import Incident
    i = db.get(Incident, iid)
    if i is None:
        raise HTTPException(404, "Incident introuvable")
    if body.status not in ("open", "ignored", "fixed"):
        raise HTTPException(400, "Statut inconnu")
    i.status = body.status
    db.commit()
    return selfcare.to_dict(i)


@router.post("/selfcare/repair")
def selfcare_repair(body: RepairIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    job = _repair_call(repair.start_job, db, body.kind, body.request, body.incident_id)
    return repair.to_dict(job)


@router.get("/selfcare/jobs/{jid}")
def selfcare_job(jid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    from app.models import RepairJob
    j = db.get(RepairJob, jid)
    if j is None:
        raise HTTPException(404, "Proposition introuvable")
    out = repair.to_dict(j)
    if j.status == "proposed":
        try:
            out["checks"] = repair.checks(db, j)
        except repair.RepairError as exc:
            out["checks"] = {"state": "unknown", "detail": str(exc)}
    return out


@router.post("/selfcare/jobs/{jid}/merge")
def selfcare_merge(jid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    from app.models import RepairJob
    j = db.get(RepairJob, jid)
    if j is None:
        raise HTTPException(404, "Proposition introuvable")
    out = _repair_call(repair.merge, db, j)
    audit(db, user.id, "repair_merge", "repair_job", j.id, j.pr_url)
    db.commit()
    return out


@router.post("/selfcare/jobs/{jid}/close")
def selfcare_close(jid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    from app.models import RepairJob
    j = db.get(RepairJob, jid)
    if j is None:
        raise HTTPException(404, "Proposition introuvable")
    _repair_call(repair.close, db, j)
    return repair.to_dict(j)


@router.get("/selfcare/github")
def selfcare_github(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    return repair.status(db)


@router.put("/selfcare/github")
def selfcare_github_connect(body: GithubIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    return _repair_call(repair.connect, db, body.token, body.repo, body.base, body.deploy_hook)


@router.delete("/selfcare/github")
def selfcare_github_disconnect(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import repair
    repair.disconnect(db)
    return repair.status(db)


@router.post("/agents")
def agents_create(body: AgentIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import agents
    try:
        return agents.to_dict(agents.create(db, body.name, body.mission, body.every_hours, by="owner"))
    except agents.AgentError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/agents/{aid}")
def agents_status(aid: str, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import agents
    from app.models import CustomAgent
    a = db.get(CustomAgent, aid)
    if a is None:
        raise HTTPException(404, "Agent introuvable")
    try:
        return agents.to_dict(agents.set_status(db, a, body.status))
    except agents.AgentError as exc:
        raise HTTPException(400, str(exc))


@router.post("/agents/{aid}/run")
def agents_run(aid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app import agents
    from app.models import CustomAgent
    a = db.get(CustomAgent, aid)
    if a is None:
        raise HTTPException(404, "Agent introuvable")
    return {"started": agents.start(a.id)}


@router.delete("/agents/{aid}")
def agents_delete(aid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    from app.models import CustomAgent
    a = db.get(CustomAgent, aid)
    if a is None:
        raise HTTPException(404, "Agent introuvable")
    db.delete(a)
    db.commit()
    return {"ok": True}
