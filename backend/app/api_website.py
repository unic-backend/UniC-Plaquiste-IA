"""Site web : connexion GitHub, rédaction d'une page par l'IA, aperçu, publication après approbation."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant, higgsfield, lessons, memory as mem, repair, video_studio, website
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


def _hf(fn, *a):
    try:
        return fn(*a)
    except higgsfield.HiggsfieldError as exc:
        raise HTTPException(exc.status, str(exc))


class VideoPlanIn(BaseModel):
    brief: str = Field("", max_length=20000)
    format: str = Field("vertical", pattern="^(vertical|horizontal|square)$")
    theme: str = Field("auto", pattern="^(auto|unic|night|light|earth|ocean|sunset|noir|luxe|papier|pastel|neon|chantier)$")   # ambiance imposée, ou « auto » : l'IA choisit
    current: dict | None = None                                                       # scénario affiché, pour une correction
    changes: list[str] = Field(default_factory=list, max_length=50)   # corrections du patron, la dernière à appliquer (le scénariste garde les 12 dernières)


class VideoStartIn(BaseModel):
    spec: dict


class VideoAIStartIn(BaseModel):
    prompt: str = Field(..., min_length=8, max_length=1500)
    duration: int = Field(5, ge=2, le=30)
    format: str = Field("vertical", pattern="^(vertical|horizontal|square)$")
    generate_audio: bool = True

class VideoAILongStartIn(BaseModel):
    prompts: list[str] = Field(..., min_length=1, max_length=20)
    duration: int = Field(..., ge=2, le=600)
    format: str = Field("vertical", pattern="^(vertical|horizontal|square)$")
    generate_audio: bool = True


@router.post("/video/plan")
def video_plan(body: VideoPlanIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Scénario proposé par l'IA pour une consigne libre, ou corrigé selon la dernière correction du patron (rien n'est lancé).
    Une correction qui vaut en général (« jamais de… », « toujours… ») devient une leçon de la mémoire, après la réponse : les vidéos suivantes en tiennent compte."""
    out = _v(video_studio.plan, db, body.brief, body.format, body.theme, body.current, body.changes)
    last = (body.changes or [""])[-1]
    if last and lessons.wants_to_learn(last, []):
        background.add_task(mem.extract_in_background, lessons.payload(f"[Studio vidéo] {last}", f"Scénario de vidéo proposé : {out.get('understood') or ''}", []))
    return out


@router.get("/video/draft")
def video_draft(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Scénario préparé dans le chat (outil plan_video), à relire puis lancer dans le Studio."""
    return video_studio.draft(db)


@router.post("/video/start")
def video_start(body: VideoStartIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron : lance la fabrication (GitHub Actions)."""
    out = _v(video_studio.start, db, body.spec, user.id)
    audit(db, user.id, "video_start", "website", "portfolio")
    db.commit()
    return out


@router.post("/video/retry")
def video_retry(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron : relance le montage avec les médias IA déjà générés (sans nouveau crédit)."""
    out = _v(video_studio.retry_render, db)
    audit(db, user.id, "video_retry", "website", "portfolio")
    db.commit()
    return out


@router.get("/video/media")
def video_media_list(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Médias du patron pour le Studio : ses vidéos de chantier, sa musique, sa voix (phrases repérées)."""
    from app import video_media
    from app import video_studio
    return {"items": video_media.listing(db), "auto_words": video_media.auto_words(db), "ai_scenes": video_studio.ai_enabled(db)}


class AutoWordsIn(BaseModel):
    on: bool


@router.post("/video/ai-scenes")
def video_ai_scenes(body: AutoWordsIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Réglage du patron : scènes IA payantes (Higgsfield) dans le Studio, plafonnées par les quotas du jour."""
    from app import video_studio
    on = video_studio.set_ai_enabled(db, body.on)
    audit(db, user.id, "video_ai_scenes", "video_studio", "ai", "oui" if on else "non")
    db.commit()
    return {"ai_scenes": on}


@router.post("/video/media/auto-words")
def video_media_auto_words(body: AutoWordsIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Réglage du patron : sous-titres créés automatiquement (crédit ElevenLabs) ou seulement au clic."""
    from app import video_media
    on = video_media.set_auto_words(db, body.on)
    audit(db, user.id, "video_auto_words", "video_media", "auto", "oui" if on else "non")
    db.commit()
    return {"auto_words": on}


@router.post("/video/media")
async def video_media_add(kind: str = Form(...), script: str = Form(""), file: UploadFile = File(...),
                          db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron : envoie une vidéo, une musique ou une voix (avec son texte, facultatif) au Studio. Rien n'est publié."""
    from app import video_media
    try:
        it = await video_media.add(db, file, kind, script[:6000])
    except video_media.MediaError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc))
    audit(db, user.id, "video_media_add", "video_media", it["id"], f"{kind} {it['name']}")
    db.commit()
    return it


@router.get("/video/media/{mid}/frame")
def video_media_frame(mid: str, t: float = 0, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Vignette d'un passage de la vidéo du patron (scénario du Studio) : la vraie image, pas un cadre vide."""
    from fastapi.responses import FileResponse

    from app import video_media
    p = video_media.frame_path(db, mid, t) if video_media.ID_RE.match(mid) else None
    if p is None:
        raise HTTPException(404, "Image introuvable.")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


class MediaKindIn(BaseModel):
    kind: str


@router.post("/video/media/{mid}/kind")
def video_media_kind(mid: str, body: MediaKindIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Le patron corrige le type d'un son d'un appui : musique <-> voix off."""
    from app import video_media
    if not video_media.ID_RE.match(mid):
        raise HTTPException(404, "Média introuvable.")
    try:
        it = video_media.set_kind(db, mid, body.kind)
    except video_media.MediaError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc))
    audit(db, user.id, "video_media_kind", "video_media", mid, body.kind[:10])
    db.commit()
    return it


@router.post("/video/media/{mid}/words")
def video_media_words(mid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic du patron « Sous-titres » : transcription mot à mot (ElevenLabs, son seulement), gardée pour les vidéos suivantes."""
    from app import video_media
    if not video_media.ID_RE.match(mid):
        raise HTTPException(404, "Média introuvable.")
    try:
        it = video_media.transcribe(db, mid)
    except video_media.MediaError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc))
    audit(db, user.id, "video_media_words", "video_media", mid, f"{it.get('words', 0)} mots")
    db.commit()
    return it


@router.post("/video/media/{mid}/hide")
def video_media_hide(mid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Retire un média de la liste (le fichier reste sur le serveur : aucune suppression)."""
    from app import video_media
    if not video_media.ID_RE.match(mid):
        raise HTTPException(404, "Média introuvable.")
    try:
        video_media.hide(db, mid)
    except video_media.MediaError as exc:
        raise HTTPException(exc.status, str(exc))
    audit(db, user.id, "video_media_hide", "video_media", mid)
    db.commit()
    return {"ok": True}


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


@router.post("/video/ai/start")
def video_ai_start(body: VideoAIStartIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Clic explicite du patron : consomme des crédits Higgsfield pour générer un clip IA de 2 à 30 secondes."""
    out = _hf(higgsfield.start_video, db, body.prompt, body.duration, body.format, body.generate_audio, user.id)
    audit(db, user.id, "video_ai_start", "higgsfield_video", str(out.get("duration") or ""))
    db.commit()
    return out


@router.post("/video/ai/long/start")
def video_ai_long_start(body: VideoAILongStartIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Lance explicitement une série de clips IA puis les assemble en MP4."""
    out = _hf(higgsfield.start_long_video, db, body.prompts, body.duration, body.format, body.generate_audio, user.id)
    audit(db, user.id, "video_ai_long_start", "higgsfield_long_video", str(body.duration))
    db.commit()
    return out


@router.get("/video/ai/status")
def video_ai_status(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Vérifie le clip IA ou le montage IA long et le range dans Documents quand il est prêt."""
    return _hf(higgsfield.video_status, db, user.id)
