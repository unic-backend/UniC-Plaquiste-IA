"""Site web : connexion GitHub, rédaction d'une page par l'IA, aperçu, publication après approbation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant, memory as mem, repair, video_studio, website
from app.database import get_db
from app.models import SocialPost, User, utcnow
from app.security import get_current_user, require_roles
from app.services import audit

router = APIRouter(prefix="/website", tags=["website"])


def _w(fn, *a, **k):
    try:
        return fn(*a, **k)
    except website.WebsiteError as exc:
        raise HTTPException(exc.status, str(exc))


class ConnectIn(BaseModel):
    token: str
    repo: str = ""
    branch: str = ""


class DraftIn(BaseModel):
    topic: str = Field(..., min_length=5, max_length=300)
    details: str = Field("", max_length=3000)


def _page(db: Session, pid: str) -> SocialPost:
    p = db.get(SocialPost, pid)
    if p is None or p.platform != "website" or p.kind != "post":
        raise HTTPException(404, "Page introuvable")
    return p


@router.get("")
def site_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return website.status(db)


@router.put("/connect")
def site_connect(body: ConnectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = _w(website.connect, db, body.token, body.repo, body.branch)
    audit(db, user.id, "website_connect", "website", "")
    db.commit()
    return out


@router.delete("")
def site_disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = website.disconnect(db)
    audit(db, user.id, "website_disconnect", "website", "")
    db.commit()
    return out


@router.post("/draft")
def site_draft(body: DraftIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not assistant.ai_available():
        raise HTTPException(503, "IA non disponible : impossible de rédiger la page.")
    d = assistant.draft_site_page(body.topic, body.details, memory=mem.block(db, body.topic))
    if d is None:
        raise HTTPException(502, "La rédaction a échoué. Réessaie.")
    p = SocialPost(platform="website", kind="post", title=d["title"][:255], body=d["text"], status="draft")
    db.add(p)
    audit(db, user.id, "website_draft", "social_post", p.id)
    db.commit()
    return {"id": p.id, "title": p.title, "body": p.body, "status": p.status}


@router.get("/preview/{pid}")
def site_preview(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _page(db, pid)
    spec = _w(website.parse, p.body)
    return {"html": _w(website.render_page, p.title, spec), "words": spec["words"], "url": f"{website.SITE_URL}/{spec['slug']}/"}


@router.post("/publish/{pid}")
def site_publish(pid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _page(db, pid)
    if p.status != "approved":
        raise HTTPException(409, "Approuve la page avant de la publier.")
    out = _w(website.publish, db, p.title, p.body)
    p.status, p.published_at = "published", utcnow()
    p.external_url, p.external_id = out["url"], out["commit"][:500]
    audit(db, user.id, "website_publish", "social_post", p.id, out["url"])
    db.commit()
    return {"id": p.id, "status": p.status, "url": out["url"], "commit": out["commit"]}


@router.get("/book/preview")
def book_preview(user: User = Depends(get_current_user)):
    """Aperçu du Book (sans script : lecture sûre dans un cadre isolé)."""
    return {"html": website.book_html(preview=True), "url": f"{website.SITE_URL}/{website.BOOK_SLUG}/"}


@router.post("/book/publish")
def book_publish(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Publie le Book sur le site : uniquement sur le clic du patron (l'interface demande confirmation)."""
    out = _w(website.publish_book, db)
    audit(db, user.id, "website_book_publish", "website", out["url"])
    db.commit()
    return {"url": out["url"], "commit": out["commit"]}


# ---------- Vidéo du portfolio (fabriquée par GitHub Actions) ----------
ADMIN = require_roles("admin", "manager")


def _v(fn, *a):
    try:
        return fn(*a)
    except repair.RepairError as exc:
        raise HTTPException(exc.status, str(exc))


class VideoPlanIn(BaseModel):
    brief: str = Field("", max_length=600)


class VideoStartIn(BaseModel):
    spec: dict


@router.post("/video/plan")
def video_plan(body: VideoPlanIn, user: User = Depends(ADMIN)):
    """Scénario proposé par l'IA (rien n'est lancé)."""
    return video_studio.plan(body.brief)


@router.post("/video/start")
def video_start(body: VideoStartIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron : lance la fabrication (GitHub Actions)."""
    out = _v(video_studio.start, db, body.spec)
    audit(db, user.id, "video_start", "website", "portfolio")
    db.commit()
    return out


@router.get("/video/status")
def video_status(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    return _v(video_studio.status, db)


@router.post("/video/fetch")
def video_fetch(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron : récupère la vidéo prête et la range dans les documents."""
    out = _v(video_studio.fetch, db, user.id)
    audit(db, user.id, "video_fetch", "artifact", out["id"])
    db.commit()
    return out
