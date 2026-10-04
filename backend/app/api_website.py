"""Site web : connexion GitHub, rédaction d'une page par l'IA, aperçu, publication après approbation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant, memory as mem, website
from app.database import get_db
from app.models import SocialPost, User, utcnow
from app.security import get_current_user
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
