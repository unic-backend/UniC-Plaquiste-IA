"""UniC Code (section du menu) : le moteur Claude Code. Projets (site, jeu, appli, script, document) livrés en ZIP avec aperçu,
et le code de l'IA elle-même (corrections, nouvelles fonctions) proposé en pull request, fusionnée seulement au clic du patron."""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, defer

from app import code_tasks, repair
from app.database import get_db
from app.models import CodeTask, RepairJob, User
from app.security import require_roles
from app.services import audit

router = APIRouter(prefix="/code", tags=["code"])
ADMIN = require_roles("admin", "manager")
FINISHED = ("done", "failed", "closed")


def _c(fn, *a):
    try:
        return fn(*a)
    except code_tasks.CodeError as exc:
        raise HTTPException(exc.status, str(exc))
    except repair.RepairError as exc:
        raise HTTPException(exc.status, str(exc))


def _task(db: Session, tid: str) -> CodeTask:
    t = db.get(CodeTask, tid)
    if t is None:
        raise HTTPException(404, "Projet introuvable")
    return t


@router.get("")
def overview(db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    code_tasks.follow_all(db)
    repair.sync_all(db)
    projects = db.query(CodeTask).options(defer(CodeTask.preview)).order_by(CodeTask.created_at.desc()).limit(30).all()
    jobs = db.query(RepairJob).filter(RepairJob.engine == "claude_code").order_by(RepairJob.created_at.desc()).limit(20).all()
    return {"github": repair.status(db), "budgets": list(code_tasks.BUDGETS),
            "projects": [code_tasks.to_dict(t) for t in projects], "app_jobs": [repair.to_dict(j) for j in jobs]}


class ProjectIn(BaseModel):
    request: str = Field(min_length=1, max_length=code_tasks.REQUEST_MAX)
    budget: str = Field(default="5", max_length=4)
    parent_id: str = Field(default="", max_length=36)


@router.post("/projects")
def start_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    t = _c(code_tasks.start, db, body.request, body.budget, body.parent_id)
    audit(db, user.id, "code_project", "code_task", t.id, body.request[:300])
    db.commit()
    return code_tasks.to_dict(t)


@router.get("/projects/{tid}")
def project(tid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    t = _task(db, tid)
    try:
        code_tasks.follow(db, t)
    except (code_tasks.CodeError, KeyError, TypeError, ValueError):   # GitHub injoignable ou réponse inattendue : état inchangé
        db.rollback()
    return code_tasks.to_dict(t)


@router.post("/projects/{tid}/close")
def close_project(tid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    t = _task(db, tid)
    code_tasks.close(db, t)
    return code_tasks.to_dict(t)


@router.delete("/projects/{tid}")
def delete_project(tid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    t = _task(db, tid)
    if t.status not in FINISHED:
        raise HTTPException(409, "Ce projet est en cours : arrête-le d'abord.")
    db.delete(t)
    audit(db, user.id, "code_delete", "code_task", tid)
    db.commit()
    return {"ok": True}


@router.get("/projects/{tid}/zip")
def project_zip(tid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    t = _task(db, tid)
    data = _c(code_tasks.download, db, t)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", t.title or "projet").strip("-")[:40] or "projet"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="UniC-Code-{slug}.zip"', "Cache-Control": "no-store"})


@router.get("/projects/{tid}/preview-link")
def preview_link(tid: str, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Lien d'aperçu valable 10 minutes : l'aperçu s'ouvre hors de l'appli (navigateur), sans en-tête de connexion."""
    t = _task(db, tid)
    if not t.preview:
        raise HTTPException(404, "Pas d'aperçu pour ce projet.")
    return {"path": f"/api/code/apercu/{t.id}?t={quote(code_tasks.preview_token(t), safe='')}"}


@router.get("/apercu/{tid}", response_class=HTMLResponse)
def apercu(tid: str, t: str = Query(default="", max_length=400), db: Session = Depends(get_db)):
    """Aperçu du projet. Code écrit par Claude : origine opaque (sandbox), aucun réseau, aucun accès à l'appli ni à ses données."""
    if not code_tasks.preview_ok(tid, t):
        raise HTTPException(403, "Lien d'aperçu expiré : rouvre-le depuis UniC Code.")
    task = db.get(CodeTask, tid)
    if task is None or not task.preview:
        raise HTTPException(404, "Pas d'aperçu.")
    return HTMLResponse(task.preview, headers={"Content-Security-Policy": code_tasks.PREVIEW_CSP, "Cache-Control": "no-store",
                                               "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})


class AppJobIn(BaseModel):
    kind: str = Field(pattern="^(fix|feature)$")
    request: str = Field(min_length=1, max_length=4000)
    budget: str = Field(default="5", max_length=4)


@router.post("/app")
def app_job(body: AppJobIn, db: Session = Depends(get_db), user: User = Depends(ADMIN)):
    """Code de l'IA elle-même : toujours Claude Code, qui lit tout le dépôt (jamais le moteur classique). Proposition en brouillon,
    fusion au clic du patron. Zones protégées : refusées par les garde-fous, comme partout."""
    job = _c(repair.start_job, db, body.kind, body.request, "", True, body.budget)
    audit(db, user.id, "code_app_job", "repair_job", job.id, body.request[:300])
    db.commit()
    return repair.to_dict(job)
