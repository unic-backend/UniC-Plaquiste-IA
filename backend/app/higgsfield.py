"""Higgsfield : génération d'images et de clips vidéo IA (API officielle).

Clés (identifiant + secret) chiffrées par secrets_box, jamais renvoyées ni journalisées. Rien ne part sans clés saisies par le patron.
Chaque image et chaque clip vidéo consomment des crédits Higgsfield. Limites : MAX_PER_DAY images et MAX_VIDEO_PER_DAY clip vidéo par jour ; aucune génération sans clic explicite.
Les médias créés sont rangés comme documents de l'appli (téléchargement, partage) ; rien n'est publié ni envoyé.
"""
from __future__ import annotations

import ipaddress
import json
import re
import time
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.config import settings
from app.models import AppSetting, new_id
from app.services import store_artifact

API = "https://api.higgsfield.ai"
IMAGE_PATH = "/higgsfield-ai/soul/v2/standard"   # modèle d'image documenté dans le démarrage rapide
VIDEO_PATH = "/alibaba/wan-3.0-prime/text-to-video"  # modèle vidéo officiel, 2 à 30 secondes
MAX_PROMPT = 1500
MAX_PER_DAY = 10
MAX_VIDEO_PER_DAY = 1  # garde-fou crédits : une génération vidéo par jour
MIN_VIDEO_SECONDS, MAX_VIDEO_SECONDS = 2, 30
MAX_VIDEO_BYTES = 60 * 1024 * 1024
VIDEO_COUNT_KEY = "higgsfield_video_count"
VIDEO_JOB_KEY = "higgsfield_video_job"
VIDEO_RATIOS = {"vertical": "9:16", "horizontal": "16:9", "square": "1:1"}
POLL_S = 3.0
MAX_WAIT_S = 150
MAX_IMAGE_BYTES = 15 * 1024 * 1024
_ID_RE = re.compile(r"^[\w-]{8,80}$")


class HiggsfieldError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def credentials(db: Session) -> tuple[str, str]:
    kid, sec = _get(db, "higgsfield_key_id"), _get(db, "higgsfield_key_secret")
    return ((secrets_box.decrypt(kid) or "") if kid else "", (secrets_box.decrypt(sec) or "") if sec else "")


def status(db: Session) -> dict:
    kid, sec = credentials(db)
    day, _, n = _get(db, "higgsfield_count").partition(":")
    used = int(n) if day == date.today().isoformat() and n.isdigit() else 0
    video_day, _, video_n = _get(db, VIDEO_COUNT_KEY).partition(":")
    video_used = int(video_n) if video_day == date.today().isoformat() and video_n.isdigit() else 0
    return {"connected": bool(kid and sec), "per_day": MAX_PER_DAY, "left_today": max(0, MAX_PER_DAY - used),
            "video_per_day": MAX_VIDEO_PER_DAY, "video_left_today": max(0, MAX_VIDEO_PER_DAY - video_used)}


def _http(method: str, url: str, creds: tuple[str, str], **kw) -> httpx.Response:
    headers = {"Authorization": f"Key {creds[0]}:{creds[1]}", **kw.pop("headers", {})}
    try:
        with httpx.Client(timeout=40) as c:
            return c.request(method, url, headers=headers, **kw)
    except httpx.HTTPError:
        raise HiggsfieldError("Higgsfield est injoignable depuis le serveur. Réessaie dans un instant.", 502)


def connect(db: Session, key_id: str, secret: str) -> dict:
    key_id, secret = (key_id or "").strip(), (secret or "").strip()
    if len(key_id) < 6 or len(secret) < 6:
        raise HiggsfieldError("Colle l'identifiant de clé ET le secret (open.higgsfield.ai).")
    # Vérification sans dépenser un crédit : une requête de statut inexistante répond 404 si les clés sont bonnes, 401 sinon.
    r = _http("GET", f"{API}/requests/{uuid.uuid4()}/status", (key_id, secret))
    if r.status_code in (401, 403):
        raise HiggsfieldError("Clés refusées par Higgsfield : vérifie l'identifiant et le secret sur open.higgsfield.ai.")
    _put(db, "higgsfield_key_id", secrets_box.encrypt(key_id))
    _put(db, "higgsfield_key_secret", secrets_box.encrypt(secret))
    db.commit()
    return status(db)


def disconnect(db: Session) -> None:
    for k in ("higgsfield_key_id", "higgsfield_key_secret"):
        row = db.get(AppSetting, k)
        if row:
            db.delete(row)
    db.commit()


def _reserve(db: Session) -> None:
    """Compte une génération AVANT de la lancer : le plafond protège les crédits même si une erreur survient ensuite."""
    st = status(db)
    if st["left_today"] <= 0:
        raise HiggsfieldError(f"Limite de {MAX_PER_DAY} images par jour atteinte : réessaie demain (protège tes crédits Higgsfield).", 429)
    _put(db, "higgsfield_count", f"{date.today().isoformat()}:{MAX_PER_DAY - st['left_today'] + 1}")
    db.commit()


def _safe_https(url: str) -> bool:
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ipaddress.ip_address(host)
        return False   # adresse IP brute : pas de requête vers le réseau interne
    except ValueError:
        return True


def _download(url: str) -> tuple[int, str, bytes]:
    try:
        with httpx.Client(timeout=60) as c:
            img = c.get(url)
    except httpx.HTTPError:
        raise HiggsfieldError("Image créée mais impossible de la télécharger : réessaie.", 502)
    return img.status_code, (img.headers.get("content-type") or "").split(";")[0].strip().lower(), img.content


def generate_image(db: Session, prompt: str, user_id: str | None) -> dict:
    """Crée UNE image à partir d'un texte, attend le résultat (150 s au plus) et la range comme document de l'appli."""
    prompt = " ".join((prompt or "").split())
    if len(prompt) < 8:
        raise HiggsfieldError("Décris l'image voulue (une phrase au moins).")
    creds = credentials(db)
    if not (creds[0] and creds[1]):
        raise HiggsfieldError("Higgsfield n'est pas connecté : Plus › Higgsfield › colle tes clés.", 400)
    _reserve(db)
    r = _http("POST", f"{API}{IMAGE_PATH}", creds, json={"prompt": prompt[:MAX_PROMPT]},
              headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    if r.status_code in (401, 403):
        raise HiggsfieldError("Clés Higgsfield refusées : reconnecte-les dans Plus › Higgsfield.")
    if r.status_code == 402 or r.status_code == 429:
        raise HiggsfieldError("Crédits Higgsfield épuisés ou trop de demandes : vérifie ton compte sur open.higgsfield.ai.", 402)
    if r.status_code >= 300:
        raise HiggsfieldError(f"Higgsfield a refusé la demande ({r.status_code}).", 502)
    sub = r.json() or {}
    rid = str(sub.get("request_id") or "")
    status_url = str(sub.get("status_url") or "")
    if not status_url.startswith(f"{API}/requests/"):
        if not _ID_RE.match(rid):
            raise HiggsfieldError("Réponse inattendue de Higgsfield.", 502)
        status_url = f"{API}/requests/{rid}/status"
    deadline = time.monotonic() + MAX_WAIT_S
    data: dict = {}
    while time.monotonic() < deadline:
        s = _http("GET", status_url, creds)
        if s.status_code >= 300:
            raise HiggsfieldError(f"Higgsfield ne répond pas correctement ({s.status_code}).", 502)
        data = s.json() or {}
        st = data.get("status")
        if st == "completed":
            break
        if st in ("failed", "nsfw", "canceled"):
            raise HiggsfieldError("Higgsfield a refusé ce contenu (modération)." if st == "nsfw" else "Higgsfield n'a pas pu créer l'image.", 422)
        time.sleep(POLL_S)
    else:
        raise HiggsfieldError("L'image met trop de temps : réessaie dans un instant (la demande peut encore aboutir chez Higgsfield).", 504)
    imgs = data.get("images") or []
    url = str((imgs[0] or {}).get("url") or "") if imgs else ""
    if not _safe_https(url):
        raise HiggsfieldError("Higgsfield n'a pas renvoyé d'image exploitable.", 502)
    code, ctype, content = _download(url)
    if code != 200 or not ctype.startswith("image/") or len(content) > MAX_IMAGE_BYTES:
        raise HiggsfieldError("Image créée mais illisible : réessaie.", 502)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(ctype, "png")
    folder = settings.artifacts_path / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    key = new_id()[:8]
    path = Path(folder) / f"visuel_{key}.{ext}"
    path.write_bytes(content)
    art = store_artifact(db, path, f"Visuel Higgsfield {key}.{ext}", "generated_image", key, f"higgsfield-{key}", user_id, mime=ctype)
    db.commit()
    return {"ok": True, "artifact": {"id": art.id, "filename": art.filename, "mime": ctype, "size": art.size},
            "restantes_aujourdhui": status(db)["left_today"]}


def _reserve_video(db: Session) -> None:
    """Réserve un crédit vidéo avant l'envoi : une requête ambiguë ne déclenche jamais de relance automatique."""
    today = date.today().isoformat()
    day, _, n = _get(db, VIDEO_COUNT_KEY).partition(":")
    used = int(n) if day == today and n.isdigit() else 0
    if used >= MAX_VIDEO_PER_DAY:
        raise HiggsfieldError(f"Limite de {MAX_VIDEO_PER_DAY} clip IA par jour atteinte : réessaie demain (protège tes crédits).", 429)
    _put(db, VIDEO_COUNT_KEY, f"{today}:{used + 1}")
    db.commit()


def _release_video_reservation(db: Session) -> None:
    """Libère le quota uniquement quand l'API a clairement refusé la requête (pas en cas de timeout ambigu)."""
    today = date.today().isoformat()
    day, _, n = _get(db, VIDEO_COUNT_KEY).partition(":")
    used = int(n) if day == today and n.isdigit() else 0
    if day == today and used > 0:
        _put(db, VIDEO_COUNT_KEY, f"{today}:{used - 1}")
        db.commit()


def _video_job(db: Session) -> dict:
    raw = _get(db, VIDEO_JOB_KEY)
    if not raw:
        return {}
    try:
        job = json.loads(raw)
    except (TypeError, ValueError):
        raise HiggsfieldError("L'état du clip IA est illisible. Réessaie depuis le Studio vidéo.", 500)
    if not isinstance(job, dict):
        raise HiggsfieldError("L'état du clip IA est illisible. Réessaie depuis le Studio vidéo.", 500)
    return job


def _save_video_job(db: Session, job: dict) -> None:
    _put(db, VIDEO_JOB_KEY, json.dumps(job, ensure_ascii=False))
    db.commit()


def _video_public(job: dict) -> dict:
    """Ne renvoie ni identifiant fournisseur, ni clé : uniquement l'état utile à l'interface."""
    out = {"state": job.get("state", "idle"), "detail": job.get("detail", ""),
           "duration": job.get("duration"), "format": job.get("format")}
    if job.get("artifact"):
        out["artifact"] = job["artifact"]
    return out


def start_video(db: Session, prompt: str, duration: int, fmt: str, generate_audio: bool, user_id: str | None) -> dict:
    """Soumet un clip IA (2–30 s). Le travail continue chez Higgsfield ; le navigateur interroge ensuite video_status."""
    prompt = " ".join((prompt or "").split())
    if len(prompt) < 8:
        raise HiggsfieldError("Décris le clip IA en une phrase (8 caractères minimum).")
    if len(prompt) > MAX_PROMPT:
        raise HiggsfieldError(f"Consigne trop longue : {MAX_PROMPT} caractères maximum.")
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        raise HiggsfieldError("Durée invalide : choisis entre 2 et 30 secondes.")
    if not MIN_VIDEO_SECONDS <= duration <= MAX_VIDEO_SECONDS:
        raise HiggsfieldError("Durée invalide : choisis entre 2 et 30 secondes.")
    ratio = VIDEO_RATIOS.get(fmt)
    if not ratio:
        raise HiggsfieldError("Format invalide : choisis vertical, horizontal ou carré.")
    creds = credentials(db)
    if not (creds[0] and creds[1]):
        raise HiggsfieldError("Higgsfield n'est pas connecté : Plus › Higgsfield › colle tes clés.", 400)
    previous = _video_job(db)
    if previous.get("state") in ("submitting", "queued", "processing"):
        raise HiggsfieldError("Un clip IA est déjà en cours. Attends sa fin avant d'en lancer un autre.", 409)

    _reserve_video(db)
    job = {"state": "submitting", "detail": "Envoi de la demande à Higgsfield…", "user_id": user_id,
           "prompt": prompt, "duration": duration, "format": fmt, "created_at": time.time(),
           "generate_audio": bool(generate_audio)}
    _save_video_job(db, job)
    try:
        response = _http("POST", f"{API}{VIDEO_PATH}", creds,
                         json={"prompt": prompt, "duration": duration, "resolution": "720p",
                               "aspect_ratio": ratio, "generate_audio": bool(generate_audio), "enable_thinking": False},
                         headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    except HiggsfieldError as exc:
        job.update(state="failed", detail=f"{exc} Si la demande a été interrompue, vérifie ton historique Higgsfield avant de relancer.")
        _save_video_job(db, job)
        raise
    if response.status_code in (401, 403):
        _release_video_reservation(db)
        job.update(state="failed", detail="Clés Higgsfield refusées : reconnecte-les dans Plus › Higgsfield.")
        _save_video_job(db, job)
        raise HiggsfieldError(job["detail"], 400)
    if response.status_code in (402, 429):
        _release_video_reservation(db)
        job.update(state="failed", detail="Crédits Higgsfield épuisés ou trop de demandes : vérifie ton compte.")
        _save_video_job(db, job)
        raise HiggsfieldError(job["detail"], 402)
    if response.status_code >= 300:
        if response.status_code < 500:
            _release_video_reservation(db)
        job.update(state="failed", detail=f"Higgsfield a refusé la demande ({response.status_code}).")
        _save_video_job(db, job)
        raise HiggsfieldError(job["detail"], 502)
    try:
        submitted = response.json() or {}
    except (TypeError, ValueError):
        submitted = {}
    if not isinstance(submitted, dict):
        submitted = {}
    request_id = str(submitted.get("request_id") or "")
    if not _ID_RE.match(request_id):
        job.update(state="failed", detail="Higgsfield n'a pas renvoyé d'identifiant de génération valide.")
        _save_video_job(db, job)
        raise HiggsfieldError(job["detail"], 502)
    job.update(state="queued", request_id=request_id, detail=f"Clip IA envoyé à Higgsfield : {duration} s, format {fmt}.")
    _save_video_job(db, job)
    return _video_public(job)


def _download_video(url: str) -> bytes:
    parsed = urlparse(url or "")
    if not _safe_https(url) or parsed.username or parsed.password:
        raise HiggsfieldError("Higgsfield n'a pas renvoyé d'adresse vidéo exploitable.", 502)
    try:
        with httpx.Client(timeout=90) as client:
            response = client.get(url)
    except httpx.HTTPError:
        raise HiggsfieldError("Le clip est prêt, mais son téléchargement a échoué. Réessaie de vérifier le statut.", 502)
    if response.status_code != 200:
        raise HiggsfieldError(f"Le téléchargement du clip a échoué ({response.status_code}).", 502)
    content = response.content
    if len(content) > MAX_VIDEO_BYTES:
        raise HiggsfieldError("Le clip dépasse la limite de stockage de 60 Mo.", 413)
    if b"ftyp" not in content[:32]:
        raise HiggsfieldError("Le fichier reçu n'est pas une vidéo MP4 valide.", 502)
    return content


def video_status(db: Session, user_id: str | None) -> dict:
    """Vérifie le job actif et range la vidéo terminée dans Documents. Appelé uniquement par l'utilisateur connecté."""
    job = _video_job(db)
    if not job:
        return {"state": "idle", "detail": "Aucun clip IA en cours."}
    if job.get("user_id") != user_id:
        raise HiggsfieldError("Ce clip IA appartient à une autre session.", 403)
    state = job.get("state")
    if state not in ("submitting", "queued", "processing"):
        return _video_public(job)
    request_id = str(job.get("request_id") or "")
    if not request_id:
        if state == "submitting" and time.time() - float(job.get("created_at") or 0) < 120:
            return _video_public(job)
        job.update(state="failed", detail="L'envoi du clip a été interrompu. Vérifie l'historique Higgsfield avant toute nouvelle demande.")
        _save_video_job(db, job)
        return _video_public(job)
    if not _ID_RE.match(request_id):
        job.update(state="failed", detail="Identifiant de génération invalide ; aucun appel externe n'a été effectué.")
        _save_video_job(db, job)
        return _video_public(job)
    creds = credentials(db)
    if not (creds[0] and creds[1]):
        return {**_video_public(job), "detail": "Higgsfield n'est plus connecté. Reconnecte les clés pour récupérer le clip."}
    try:
        response = _http("GET", f"{API}/requests/{request_id}/status", creds)
    except HiggsfieldError:
        return {**_video_public(job), "detail": "Higgsfield est temporairement injoignable ; nouvelle vérification automatique."}
    if response.status_code in (401, 403):
        return {**_video_public(job), "detail": "Clés Higgsfield refusées. Reconnecte-les pour récupérer le clip."}
    if response.status_code >= 500 or response.status_code == 429:
        return {**_video_public(job), "detail": "Higgsfield est temporairement indisponible ; nouvelle vérification automatique."}
    if response.status_code >= 300:
        job.update(state="failed", detail=f"Higgsfield ne retrouve pas cette génération ({response.status_code}).")
        _save_video_job(db, job)
        return _video_public(job)
    try:
        data = response.json() or {}
    except (TypeError, ValueError):
        return {**_video_public(job), "detail": "Réponse Higgsfield illisible ; nouvelle vérification automatique."}
    if not isinstance(data, dict):
        return {**_video_public(job), "detail": "Réponse Higgsfield illisible ; nouvelle vérification automatique."}
    provider_state = str(data.get("status") or "").lower()
    if provider_state in ("queued", "pending", "submitted"):
        job.update(state="queued", detail="Clip IA en file d'attente chez Higgsfield…")
        _save_video_job(db, job)
        return _video_public(job)
    if provider_state in ("in_progress", "processing", "running"):
        job.update(state="processing", detail="Higgsfield génère le clip IA…")
        _save_video_job(db, job)
        return _video_public(job)
    if provider_state in ("failed", "nsfw", "canceled", "cancelled"):
        job.update(state="failed", detail="Higgsfield a refusé ce contenu." if provider_state == "nsfw" else "Higgsfield n'a pas pu terminer le clip.")
        _save_video_job(db, job)
        return _video_public(job)
    if provider_state != "completed":
        job.update(state="processing", detail="Higgsfield prépare le résultat du clip IA…")
        _save_video_job(db, job)
        return _video_public(job)

    video = data.get("video") or {}
    url = str(video.get("url") or "") if isinstance(video, dict) else ""
    try:
        content = _download_video(url)
    except HiggsfieldError as exc:
        job.update(state="failed", detail=str(exc))
        _save_video_job(db, job)
        return _video_public(job)
    folder = settings.artifacts_path / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    key = new_id()[:8]
    path = Path(folder) / f"clip_ia_{key}.mp4"
    path.write_bytes(content)
    art = store_artifact(db, path, f"Clip IA Higgsfield {key}.mp4", "generated_video", key,
                         f"higgsfield-video-{key}", user_id, mime="video/mp4")
    db.commit()
    job.update(state="ready", detail=f"Clip IA prêt ({job.get('duration')} s). Enregistré dans tes documents.",
               artifact={"id": art.id, "filename": art.filename, "size": art.size,
                         "url": f"/api/artifacts/{art.id}/download"})
    _save_video_job(db, job)
    return _video_public(job)
