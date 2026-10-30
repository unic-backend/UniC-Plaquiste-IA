"""Vidéo hybride : des scènes générées par l'IA (clips et images Higgsfield) mêlées au montage Chrome + FFmpeg de GitHub.

Parcours : l'IA du Studio écrit un scénario où certaines scènes sont `ai_clip` (film de 2 à 30 s) ou `ai_image` (image animée) ;
le patron voit le nombre de scènes payantes et confirme ; CE module génère les médias chez Higgsfield, UN à la fois (un échec arrête la chaîne,
aucune relance automatique), puis lance le montage GitHub avec les adresses des médias. Le travail avance dans un fil du serveur
(l'application peut être fermée) ; un verrou fichier évite deux fils, et l'appel d'état relance un fil perdu (redémarrage du serveur).

Garde-fous : crédits payants réservés juste avant chaque envoi et rendus si le refus est net (même règle que higgsfield.py), plafonds
journaliers de higgsfield.py, adresses de médias prises UNIQUEMENT dans la réponse du fournisseur (https, jamais une IP), revalidées par le moteur.
Les films sont muets dans le montage (la voix et la musique viendront d'une étape séparée).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app import higgsfield as hf
from app.config import settings

KEY = "video_hybrid_job"
AI_TYPES = ("ai_clip", "ai_image")
POLL_S = 4.0
LOCK_STALE_S = 90          # un fil qui n'a pas battu depuis 90 s est considéré perdu
MAX_TOTAL_S = 3 * 3600     # un job qui dure plus de 3 h est abandonné
ACTIVE = ("assets",)
MAX_AI = 200               # garde-fou technique par type ; les vrais plafonds sont les quotas journaliers de higgsfield.py


class HybridError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ---------- utilitaires de scénario ----------

def ai_counts(spec: dict) -> tuple[int, int]:
    """(nombre de clips IA, nombre d'images IA) d'un scénario."""
    scenes = (spec or {}).get("scenes") or []
    return (sum(1 for s in scenes if s.get("type") == "ai_clip"), sum(1 for s in scenes if s.get("type") == "ai_image"))


def to_engine(spec: dict, assets: dict) -> dict:
    """Scénario pour le moteur : chaque scène IA devient un `clip` ou une `photo` avec l'adresse du média généré."""
    scenes = []
    for i, s in enumerate(spec["scenes"]):
        if s.get("type") == "ai_clip":
            scenes.append({"type": "clip", "url": assets[str(i)]["url"], "seconds": s["seconds"], **({"overlay": s["overlay"]} if s.get("overlay") else {})})
        elif s.get("type") == "ai_image":
            scenes.append({"type": "photo", "url": assets[str(i)]["url"], "seconds": s["seconds"], "caption": s.get("caption", ""), "direction": s.get("direction", "in")})
        else:
            scenes.append(s)
    return {**spec, "scenes": scenes}


# ---------- état (un seul travail à la fois, dans AppSetting) ----------

def _job(db: Session) -> dict:
    raw = hf._get(db, KEY)
    if not raw:
        return {}
    try:
        job = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return job if isinstance(job, dict) else {}


def _save(db: Session, job: dict) -> None:
    job["updated_at"] = time.time()
    hf._put(db, KEY, json.dumps(job, ensure_ascii=False))
    db.commit()


def clear(db: Session) -> None:
    """Oublie le travail (après récupération de la vidéo, ou quand un montage ordinaire démarre)."""
    if hf._get(db, KEY):
        hf._put(db, KEY, "")
        db.commit()


def public(db: Session) -> dict | None:
    """État utile à l'interface (jamais d'identifiant ni d'adresse du fournisseur)."""
    job = _job(db)
    if not job:
        return None
    order = job.get("order") or []
    done = sum(1 for k in order if job["assets"][k]["state"] == "done")
    return {"state": job.get("state"), "detail": job.get("detail", ""), "done": done, "total": len(order),
            "can_retry": bool(job.get("can_retry")), "dispatched_at": job.get("dispatched_at")}


# ---------- Higgsfield : un média à la fois ----------

def _release_image(db: Session) -> None:
    from datetime import date
    today = date.today().isoformat()
    day, _, n = hf._get(db, "higgsfield_count").partition(":")
    used = int(n) if day == today and n.isdigit() else 0
    if day == today and used > 0:
        hf._put(db, "higgsfield_count", f"{today}:{used - 1}")
        db.commit()


def _fail(db: Session, job: dict, detail: str, *, release: str = "") -> dict:
    if release == "clip":
        hf._release_video_reservation(db)
    elif release == "image":
        _release_image(db)
    job.update(state="failed", detail=detail, can_retry=False)
    _save(db, job)
    return job


def _submit(db: Session, job: dict, key: str, creds: tuple[str, str]) -> dict:
    a = job["assets"][key]
    clip = a["kind"] == "clip"
    try:
        (hf._reserve_video if clip else hf._reserve)(db)
    except hf.HiggsfieldError as exc:
        return _fail(db, job, f"{exc} Les médias déjà générés sont conservés chez Higgsfield ; rien d'autre n'a été lancé.")
    body = ({"prompt": a["prompt"], "duration": int(a["seconds"]), "resolution": "720p", "aspect_ratio": hf.VIDEO_RATIOS[job["format"]],
             "generate_audio": False, "enable_thinking": False} if clip else {"prompt": a["prompt"]})
    kind = "clip" if clip else "image"
    try:
        r = hf._http("POST", f"{hf.API}{hf.VIDEO_PATH if clip else hf.IMAGE_PATH}", creds, json=body,
                     headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    except hf.HiggsfieldError as exc:
        # requête ambiguë : on ne libère PAS le crédit et on ne relance pas (peut-être partie)
        return _fail(db, job, f"{exc} Si la demande est partie, vérifie ton historique Higgsfield avant de relancer.")
    if r.status_code in (401, 403):
        return _fail(db, job, "Clés Higgsfield refusées : reconnecte-les dans Plus › Higgsfield.", release=kind)
    if r.status_code in (402, 429):
        return _fail(db, job, "Crédits Higgsfield épuisés ou trop de demandes : vérifie ton compte.", release=kind)
    if r.status_code >= 300:
        return _fail(db, job, f"Higgsfield a refusé la demande ({r.status_code}).", release=kind if r.status_code < 500 else "")
    try:
        sub = r.json() or {}
    except (TypeError, ValueError):
        sub = {}
    rid = str(sub.get("request_id") or "") if isinstance(sub, dict) else ""
    if not hf._ID_RE.match(rid):
        return _fail(db, job, "Higgsfield n'a pas renvoyé d'identifiant de génération valide.")
    a.update(state="submitted", request_id=rid, started_at=time.time())
    job["detail"] = f"Média {job['cursor'] + 1}/{len(job['order'])} envoyé à Higgsfield ({'clip' if clip else 'image'})."
    _save(db, job)
    return job


def _poll(db: Session, job: dict, key: str, creds: tuple[str, str]) -> dict:
    a = job["assets"][key]
    n, total = job["cursor"] + 1, len(job["order"])
    try:
        r = hf._http("GET", f"{hf.API}/requests/{a['request_id']}/status", creds)
        data = r.json() if r.status_code < 300 else {}
    except (hf.HiggsfieldError, ValueError):
        return job                      # panne passagère : on réessaie au prochain passage
    if not isinstance(data, dict):
        return job
    st = str(data.get("status") or "").lower()
    if st in ("failed", "nsfw", "canceled", "cancelled"):
        return _fail(db, job, f"Le média {n}/{total} a échoué chez Higgsfield{' (modération)' if st == 'nsfw' else ''} ; la chaîne est arrêtée, rien d'autre n'a été lancé.")
    if st != "completed":
        job["detail"] = f"Média {n}/{total} : génération Higgsfield en cours."
        _save(db, job)
        return job
    clip = a["kind"] == "clip"
    media = data.get("video") if clip else (data.get("images") or [None])[0]
    url = str((media or {}).get("url") or "") if isinstance(media, dict) else ""
    if not hf._safe_https(url):
        return _fail(db, job, f"Higgsfield n'a pas renvoyé d'adresse exploitable pour le média {n}/{total}.")
    a.update(state="done", url=url)
    job["cursor"] += 1
    job["detail"] = f"Média {n}/{total} prêt."
    _save(db, job)
    return job


def step(db: Session) -> dict:
    """Un pas de travail : envoyer le prochain média, ou interroger celui en cours, ou lancer le montage quand tout est prêt."""
    job = _job(db)
    if not job or job.get("state") not in ACTIVE:
        return job
    if time.time() - float(job.get("created_at") or 0) > MAX_TOTAL_S:
        return _fail(db, job, "Génération trop longue : abandonnée. Vérifie ton historique Higgsfield.")
    creds = hf.credentials(db)
    if not all(creds):
        return _fail(db, job, "Higgsfield n'est plus connecté : reconnecte les clés.")
    if job["cursor"] >= len(job["order"]):
        return _render(db, job)
    key = job["order"][job["cursor"]]
    a = job["assets"][key]
    if a["state"] == "pending":
        return _submit(db, job, key, creds)
    if a["state"] == "submitted":
        return _poll(db, job, key, creds)
    job["cursor"] += 1
    _save(db, job)
    return job


def _render(db: Session, job: dict) -> dict:
    """Tous les médias sont prêts : lancement du montage GitHub."""
    from app import repair, video_studio
    try:
        video_studio.dispatch(db, to_engine(job["spec"], job["assets"]))
    except repair.RepairError as exc:
        job.update(state="failed", can_retry=True, detail=f"Les médias IA sont prêts, mais le lancement du montage a échoué : {exc} Rien n'est perdu : « Relancer le montage » sans nouveau crédit.")
        _save(db, job)
        return job
    job.update(state="rendering", detail="Médias IA prêts : montage GitHub en cours.", dispatched_at=time.time())
    _save(db, job)
    return job


def retry_render(db: Session) -> dict:
    """Clic du patron : relance le montage avec les médias déjà générés (aucun crédit)."""
    job = _job(db)
    if not job or job.get("state") != "failed" or not job.get("can_retry"):
        raise HybridError("Rien à relancer.", 409)
    job["state"] = "assets"
    job["can_retry"] = False
    _save(db, job)
    return _render(db, job)


# ---------- fil du serveur ----------

def _lock_path() -> Path:
    return settings.data_path / "video_hybrid.lock"


def _acquire() -> bool:
    lock = _lock_path()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime < LOCK_STALE_S:
                return False
            lock.unlink(missing_ok=True)          # fil perdu (serveur redémarré) : on reprend
            return _acquire()
        except OSError:
            return False


def _driver() -> None:
    from app.database import SessionLocal
    lock = _lock_path()
    try:
        while True:
            db = SessionLocal()
            try:
                job = step(db)
                active = bool(job) and job.get("state") in ACTIVE
            except Exception:           # noqa: BLE001 — un fil ne doit jamais mourir en silence : on note l'échec, sans relancer d'envoi
                db.rollback()
                job = _job(db)
                if job and job.get("state") in ACTIVE:
                    _fail(db, job, "Erreur interne pendant la génération. Vérifie ton historique Higgsfield avant de relancer.")
                active = False
            finally:
                db.close()
            if not active:
                break
            try:
                os.utime(lock)                  # battement : « ce fil est vivant »
            except OSError:
                break
            time.sleep(POLL_S)
    finally:
        lock.unlink(missing_ok=True)


def ensure_driver() -> None:
    """Lance le fil s'il n'y en a pas déjà un (aussi appelé par l'état, pour reprendre après un redémarrage du serveur)."""
    if _acquire():
        threading.Thread(target=_driver, name="video-hybride", daemon=True).start()


# ---------- démarrage (clic du patron) ----------

def start(db: Session, spec: dict, user_id: str | None) -> dict:
    clips, images = ai_counts(spec)
    if clips + images == 0:
        raise HybridError("Aucune scène IA dans ce scénario.")
    st = hf.status(db)
    if not st["connected"]:
        raise HybridError("Higgsfield n'est pas connecté : Plus › Higgsfield › colle tes clés.")
    if clips > st["video_left_today"] or images > st["left_today"]:
        raise HybridError(f"Plafond du jour : il reste {st['video_left_today']} clip(s) et {st['left_today']} image(s) IA ; ce scénario en demande {clips} et {images}.", 429)
    previous = _job(db)
    if previous.get("state") in ACTIVE:
        raise HybridError("Une génération IA est déjà en cours. Attends sa fin.", 409)
    order, assets = [], {}
    for i, s in enumerate(spec["scenes"]):
        if s.get("type") in AI_TYPES:
            order.append(str(i))
            assets[str(i)] = {"kind": "clip" if s["type"] == "ai_clip" else "image", "prompt": s["prompt"], "seconds": s["seconds"], "state": "pending"}
    job = {"state": "assets", "user_id": user_id, "format": spec.get("format", "vertical"), "spec": spec, "order": order, "assets": assets, "cursor": 0,
           "detail": f"Génération IA : {clips} clip(s), {images} image(s), l'un après l'autre.", "created_at": time.time(), "can_retry": False}
    _save(db, job)
    ensure_driver()
    return {"ok": True, "ai": {"clips": clips, "images": images},
            "note": f"Génération IA lancée ({clips} clip(s), {images} image(s)) puis montage. Tu peux fermer l'application : le travail continue."}
