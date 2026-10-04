"""API Réseaux sociaux, Fiche Google, site web et boîte mail.

Règle : rien ne part sans approbation explicite du patron. Les connecteurs
absents répondent NON DISPONIBLE.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant, connectors, google_business as gbp, mailbox, memory as mem
from app.database import get_db
from app.models import EmailDraft, InboxMessage, SocialAccount, SocialPost, User, utcnow
from app.security import get_current_user
from app.services import audit
from app.social import AUTO_PUBLISH_NOTE, NEXT_STATUS, PLATFORMS, check_post

logger = logging.getLogger("unic.reseaux")
router = APIRouter()

NO_AI = "IA NON DISPONIBLE : aucun fournisseur IA configuré (OPENAI_API_KEY ou LOCAL_AI_URL)."


def _post_out(p: SocialPost) -> dict:
    return {
        "id": p.id, "platform": p.platform, "kind": p.kind, "title": p.title, "body": p.body,
        "hashtags": p.hashtags, "in_reply_to": p.in_reply_to, "status": p.status,
        "external_url": p.external_url, "external_id": p.external_id, "created_at": p.created_at.isoformat() if p.created_at else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
    }


def _get_post(db: Session, pid: str) -> SocialPost:
    p = db.get(SocialPost, pid)
    if p is None:
        raise HTTPException(404, "Publication introuvable")
    return p


# ---------- plateformes ----------

@router.get("/reseaux/platforms")
def platforms(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    accounts = {a.platform: a for a in db.query(SocialAccount).all()}
    out = []
    for pid, spec in PLATFORMS.items():
        acc = accounts.get(pid)
        out.append({
            "id": pid, "label": spec["label"], "description": spec["desc"], "tip": spec["tip"],
            "max_chars": spec["max"],
            "linked": bool(acc and acc.linked),
            "handle": acc.handle if acc else "", "page_url": acc.page_url if acc else "",
            "auto_publish": False,
        })
    return {"platforms": out, "auto_publish_note": AUTO_PUBLISH_NOTE, "ai_available": assistant.ai_available()}


class AccountIn(BaseModel):
    handle: str = Field("", max_length=255)
    page_url: str = Field("", max_length=512)
    linked: bool = True


@router.put("/reseaux/accounts/{platform}")
def set_account(platform: str, body: AccountIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if platform not in PLATFORMS:
        raise HTTPException(404, "Plateforme inconnue")
    if body.page_url and not body.page_url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "URL invalide (http:// ou https://)")
    acc = db.query(SocialAccount).filter(SocialAccount.platform == platform).first()
    if acc is None:
        acc = SocialAccount(platform=platform)
        db.add(acc)
    acc.handle, acc.page_url, acc.linked = body.handle.strip(), body.page_url.strip(), body.linked
    audit(db, user.id, "social_account", "social_account", platform)
    db.commit()
    return {"platform": platform, "linked": acc.linked, "handle": acc.handle, "page_url": acc.page_url}


# ---------- publications ----------

class PostIn(BaseModel):
    platform: str
    kind: str = Field("post", pattern="^(post|reply)$")
    title: str = Field("", max_length=255)
    body: str
    hashtags: str = Field("", max_length=512)
    in_reply_to: str = Field("", max_length=5000)


@router.get("/reseaux/posts")
def list_posts(platform: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(SocialPost)
    if platform:
        q = q.filter(SocialPost.platform == platform)
    return [_post_out(p) for p in q.order_by(SocialPost.created_at.desc()).limit(200).all()]


@router.post("/reseaux/posts")
def create_post(body: PostIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    err = check_post(body.platform, body.body, body.hashtags)
    if err:
        raise HTTPException(400, err)
    p = SocialPost(platform=body.platform, kind=body.kind, title=body.title.strip(), body=body.body.strip(),
                   hashtags=body.hashtags.strip(), in_reply_to=body.in_reply_to.strip())
    db.add(p)
    db.flush()
    audit(db, user.id, "social_draft", "social_post", p.id, p.platform)
    db.commit()
    return _post_out(p)


class PostEdit(BaseModel):
    title: str | None = Field(None, max_length=255)
    body: str | None = None
    hashtags: str | None = Field(None, max_length=512)


@router.patch("/reseaux/posts/{pid}")
def edit_post(pid: str, body: PostEdit, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _get_post(db, pid)
    if p.status in ("approved", "published"):
        raise HTTPException(409, "Texte figé après approbation. Créez un nouveau brouillon.")
    if body.title is not None:
        p.title = body.title.strip()
    if body.body is not None:
        p.body = body.body.strip()
    if body.hashtags is not None:
        p.hashtags = body.hashtags.strip()
    err = check_post(p.platform, p.body, p.hashtags)
    if err:
        raise HTTPException(400, err)
    db.commit()
    return _post_out(p)


@router.post("/reseaux/posts/{pid}/advance")
def advance_post(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """draft → review → approved → published (marqué à la main après publication réelle)."""
    p = _get_post(db, pid)
    nxt = NEXT_STATUS.get(p.status)
    if nxt is None:
        raise HTTPException(409, "Déjà publié")
    if nxt == "published":
        p.published_at = utcnow()
    p.status = nxt
    audit(db, user.id, f"social_{nxt}", "social_post", p.id, p.platform)
    db.commit()
    return _post_out(p)


@router.post("/reseaux/posts/{pid}/publish")
def publish_post(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Publication réelle : uniquement fiche Google, texte approuvé, configuration complète."""
    p = _get_post(db, pid)
    if p.platform != "google_business":
        raise HTTPException(501, "Publication automatique NON DISPONIBLE pour cette plateforme. Publiez à la main.")
    if p.status != "approved":
        raise HTTPException(409, "Approuvez le texte avant la publication.")
    try:
        if p.kind == "reply":
            if not p.external_id:
                raise HTTPException(400, "Avis visé inconnu : créez la réponse depuis la liste des avis Google.")
            gbp.reply_review(p.external_id, p.body)
        else:
            p.external_id = gbp.create_post(p.body, p.hashtags if p.hashtags.startswith("http") else "")
    except gbp.GoogleError as exc:
        raise HTTPException(502, f"Publication échouée, rien n'a été publié. {exc}")
    p.status = "published"
    p.published_at = utcnow()
    audit(db, user.id, "google_publish", "social_post", p.id, p.kind)
    db.commit()
    return _post_out(p)


@router.delete("/reseaux/posts/{pid}")
def delete_post(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _get_post(db, pid)
    db.delete(p)
    audit(db, user.id, "social_delete", "social_post", pid)
    db.commit()
    return {"ok": True}


class GenerateIn(BaseModel):
    platform: str
    topic: str = Field("", max_length=500)
    details: str = Field("", max_length=3000)
    comment: str = Field("", max_length=3000)  # commentaire/avis à qui répondre
    instruction: str = Field("", max_length=500)


@router.post("/reseaux/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.platform not in PLATFORMS:
        raise HTTPException(404, "Plateforme inconnue")
    if not assistant.ai_available():
        raise HTTPException(503, NO_AI)
    if body.comment:
        text = assistant.reply_to_comment(body.platform, body.comment, body.instruction, memory=mem.block(db, body.comment))
    elif body.topic:
        text = assistant.draft_post(body.platform, body.topic, body.details, memory=mem.block(db, body.topic))
    else:
        raise HTTPException(400, "Donnez un sujet ou un commentaire")
    if not text:
        raise HTTPException(502, "L'IA n'a rien produit. Réessayez.")
    return {"text": text, "warning": check_post(body.platform, text)}


class BoostIn(BaseModel):
    deep: bool = False
    target: str = Field(..., max_length=300)  # ex. « fiche Google », « site web », « Instagram »
    facts: str = Field("", max_length=3000)


@router.post("/reseaux/boost")
def boost(body: BoostIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not assistant.ai_available():
        raise HTTPException(503, NO_AI)
    plan = assistant.boost_plan(body.target, body.facts, body.deep, mem.block(db, body.target))
    if not plan:
        raise HTTPException(502, "L'IA n'a rien produit. Réessayez.")
    return {"plan": plan, "note": "Conseils uniquement. Aucune action n'est lancée, aucun budget dépensé."}


# ---------- boîte mail ----------

def _mail_out(m: InboxMessage) -> dict:
    return {"id": m.id, "from_addr": m.from_addr, "subject": m.subject, "date": m.date,
            "body": m.body, "summary": m.summary, "category": m.category,
            "reply_draft_id": m.reply_draft_id}


@router.get("/mail/status")
def mail_status(user: User = Depends(get_current_user)):
    return {
        "read": mailbox.imap_configured(), "send": mailbox.smtp_configured(),
        "ai": assistant.ai_available(),
        "note": "" if mailbox.imap_configured() else "Lecture NON DISPONIBLE : IMAP_HOST / SMTP_USER non configurés.",
    }


@router.post("/mail/sync")
def mail_sync(limit: int = 20, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return connectors.sync_inbox(db, limit)
    except connectors.ConnectorError as exc:
        raise HTTPException(exc.status, str(exc))


@router.get("/mail")
def mail_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [_mail_out(m) for m in db.query(InboxMessage).order_by(InboxMessage.fetched_at.desc()).limit(100).all()]


def _get_mail(db: Session, mid: str) -> InboxMessage:
    m = db.get(InboxMessage, mid)
    if m is None:
        raise HTTPException(404, "Message introuvable")
    return m


@router.post("/mail/{mid}/analyze")
def mail_analyze(mid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = _get_mail(db, mid)
    if not assistant.ai_available():
        raise HTTPException(503, NO_AI)
    res = assistant.analyze_email(m.from_addr, m.subject, m.body, mem.block(db, m.subject))
    if res is None:
        raise HTTPException(502, "Analyse impossible")
    m.summary = str(res.get("summary", ""))[:1000]
    m.category = str(res.get("category", ""))[:32]
    db.commit()
    return {**_mail_out(m), "priority": res.get("priority", ""), "action": res.get("action", "")}


class ReplyIn(BaseModel):
    deep: bool = False
    instruction: str = Field("", max_length=500)


@router.post("/mail/{mid}/reply-draft")
def mail_reply_draft(mid: str, body: ReplyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = _get_mail(db, mid)
    if not assistant.ai_available():
        raise HTTPException(503, NO_AI)
    text = assistant.propose_reply(m.from_addr, m.subject, m.body, body.instruction, body.deep, mem.block(db, m.subject + " " + body.instruction))
    if not text:
        raise HTTPException(502, "L'IA n'a rien produit. Réessayez.")
    subject = m.subject if m.subject.lower().startswith("re:") else f"Re: {m.subject}"
    d = EmailDraft(to_addr=m.from_addr, subject=subject, body=text, status="draft",
                   related_type="inbox", related_id=m.id, created_by=user.id)
    db.add(d)
    db.flush()
    m.reply_draft_id = d.id
    audit(db, user.id, "mail_reply_draft", "email_draft", d.id)
    db.commit()
    return {"id": d.id, "to_addr": d.to_addr, "subject": d.subject, "body": d.body, "status": d.status}


class DraftEdit(BaseModel):
    to_addr: str | None = Field(None, max_length=255)
    subject: str | None = Field(None, max_length=512)
    body: str | None = None


def _get_draft(db: Session, did: str) -> EmailDraft:
    d = db.get(EmailDraft, did)
    if d is None:
        raise HTTPException(404, "Brouillon introuvable")
    return d


@router.patch("/mail/drafts/{did}")
def mail_draft_edit(did: str, body: DraftEdit, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _get_draft(db, did)
    if d.status != "draft":
        raise HTTPException(409, "Brouillon figé après approbation.")
    for field in ("to_addr", "subject", "body"):
        v = getattr(body, field)
        if v is not None:
            setattr(d, field, v)
    db.commit()
    return {"id": d.id, "to_addr": d.to_addr, "subject": d.subject, "body": d.body, "status": d.status}


@router.post("/mail/drafts/{did}/approve")
def mail_draft_approve(did: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _get_draft(db, did)
    if d.status != "draft":
        raise HTTPException(409, f"Statut actuel : {d.status}")
    if "@" not in d.to_addr:
        raise HTTPException(400, "Adresse du destinataire manquante")
    d.status = "approved"
    audit(db, user.id, "mail_approve", "email_draft", d.id)
    db.commit()
    return {"id": d.id, "status": d.status}


@router.post("/mail/drafts/{did}/send")
def mail_draft_send(did: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = _get_draft(db, did)
    if d.status != "approved":
        raise HTTPException(409, "Approuvez le brouillon avant l'envoi.")
    if not mailbox.smtp_configured():
        raise HTTPException(503, "Envoi NON DISPONIBLE : SMTP non configuré. Copiez le texte.")
    try:
        mailbox.send(d.to_addr, d.subject, d.body)
    except Exception as exc:
        logger.warning("SMTP échec : %s", exc)
        raise HTTPException(502, "Envoi échoué. Rien n'a été envoyé. Vérifiez la configuration SMTP.")
    d.status = "sent"
    audit(db, user.id, "mail_sent", "email_draft", d.id, d.to_addr)
    db.commit()
    return {"id": d.id, "status": d.status}


# ---------- fiche Google ----------

def _gbp_guard() -> None:
    if not gbp.configured():
        raise HTTPException(503, "Fiche Google NON DISPONIBLE : configuration incomplète (" + ", ".join(gbp.missing_settings()) + ").")


def _gbp_call(fn, *args):
    try:
        return fn(*args)
    except gbp.GoogleError as exc:
        raise HTTPException(502, str(exc))


@router.get("/google/status")
def google_status(user: User = Depends(get_current_user)):
    return {"configured": gbp.configured(), "missing": gbp.missing_settings(), "ai": assistant.ai_available()}


@router.get("/google/profile")
def google_profile(user: User = Depends(get_current_user)):
    _gbp_guard()
    return gbp.audit_location(_gbp_call(gbp.get_location))


@router.get("/google/reviews")
def google_reviews(user: User = Depends(get_current_user)):
    _gbp_guard()
    return _gbp_call(gbp.list_reviews)


class ReviewReplyIn(BaseModel):
    comment: str = Field(..., max_length=4000)
    stars: int = Field(0, ge=0, le=5)
    instruction: str = Field("", max_length=500)


@router.post("/google/reviews/{review_id}/reply-draft")
def google_reply_draft(review_id: str, body: ReviewReplyIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Crée un brouillon de réponse à un avis (à approuver puis publier)."""
    if not gbp.REVIEW_ID_RE.match(review_id):
        raise HTTPException(400, "Identifiant d'avis invalide")
    if not assistant.ai_available():
        raise HTTPException(503, NO_AI)
    hint = f"Note de l'avis : {body.stars}/5. " if body.stars else ""
    text = assistant.reply_to_comment("google_business", body.comment, hint + body.instruction, memory=mem.block(db, body.comment))
    if not text:
        raise HTTPException(502, "L'IA n'a rien produit. Réessayez.")
    err = check_post("google_business", text)
    if err:
        raise HTTPException(502, err)
    p = SocialPost(platform="google_business", kind="reply", body=text.strip(),
                   in_reply_to=body.comment[:5000], external_id=review_id)
    db.add(p)
    db.flush()
    audit(db, user.id, "google_reply_draft", "social_post", p.id)
    db.commit()
    return _post_out(p)


# ---------- mémoire ----------

class MemoryIn(BaseModel):
    text: str = Field(..., min_length=5, max_length=mem.MAX_TEXT)
    kind: str = Field("fact", pattern="^(fact|preference|correction|task)$")
    pinned: bool = False


class MemoryDecision(BaseModel):
    action: str = Field(..., pattern="^(confirm|reject|archive|restore|pin|unpin)$")


def _mem_out(m) -> dict:
    return {"id": m.id, "text": m.text, "kind": m.kind, "source": m.source, "pinned": m.pinned, "nature": m.nature,
            "state": m.state, "importance": m.importance, "occurrences": m.occurrences,
            "expires_at": m.expires_at.isoformat() if m.expires_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None}


@router.get("/memory")
def memory_list(state: str = "active", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Memory
    q = db.query(Memory)
    if state != "all":
        q = q.filter(Memory.state == state)
    return [_mem_out(m) for m in q.order_by(Memory.pinned.desc(), Memory.created_at.desc()).all()]


@router.get("/memory/conflicts")
def memory_conflicts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return mem.conflicts(db)


@router.get("/memory/state")
def memory_state(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return mem.state_report(db)


@router.get("/memory/search")
def memory_search(q: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ce que l'IA retrouverait pour cette question, et pourquoi."""
    return [{**_mem_out(h.memory), "pourquoi": h.why()} for h in mem.retrieve(db, q)]


@router.post("/memory")
def memory_add(body: MemoryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        m = mem.add(db, body.text, kind=body.kind, source="user", pinned=body.pinned)
    except mem.MemoryRefused as refus:
        raise HTTPException(422, str(refus))
    db.commit()   # garde le compteur d'occurrences d'un doublon
    if m is None:
        raise HTTPException(409, "Déjà en mémoire (compté une fois de plus) ou trop court")
    return _mem_out(m)


@router.patch("/memory/{mid}")
def memory_decide(mid: str, body: MemoryDecision, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = mem.decide(db, mid, body.action)
    if m is None:
        raise HTTPException(404, "Souvenir introuvable")
    audit(db, user.id, f"memory_{body.action}", "memory", mid)
    db.commit()
    return _mem_out(m)


@router.post("/memory/import")
async def memory_import(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Importe un export ChatGPT / Claude (json, zip) ou un texte : suppositions à confirmer, jamais des faits."""
    raw = await file.read()
    if len(raw) > 60 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (60 Mo max)")
    try:
        texts = mem.candidates_from_export(raw, file.filename or "")
    except mem.UnknownImport as exc:
        raise HTTPException(400, str(exc))
    result = mem.import_candidates(db, texts)
    audit(db, user.id, "memory_import", "memory", file.filename or "", str(result))
    db.commit()
    return {**result, "candidats": len(texts)}


@router.delete("/memory/{mid}")
def memory_delete(mid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Memory
    m = db.get(Memory, mid)
    if m is None:
        raise HTTPException(404, "Souvenir introuvable")
    db.delete(m)
    db.commit()
    return {"ok": True}
