"""Higgsfield : génération d'images (API officielle, docs.higgsfield.ai).

Clés (identifiant + secret) chiffrées par secrets_box, jamais renvoyées ni journalisées. Rien ne part sans clés saisies par le patron.
Chaque image consomme ses crédits Higgsfield : une image par demande, plafond de MAX_PER_DAY par jour, jamais lancée en arrière-plan.
L'image créée est rangée comme document de l'appli (téléchargement, partage) ; rien n'est publié ni envoyé.
"""
from __future__ import annotations

import ipaddress
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
MAX_PROMPT = 1500
MAX_PER_DAY = 10
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
    return {"connected": bool(kid and sec), "per_day": MAX_PER_DAY, "left_today": max(0, MAX_PER_DAY - used)}


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
        raise HiggsfieldError("Colle l'identifiant de clé ET le secret (console.higgsfield.ai).")
    # Vérification sans dépenser un crédit : une requête de statut inexistante répond 404 si les clés sont bonnes, 401 sinon.
    r = _http("GET", f"{API}/requests/{uuid.uuid4()}/status", (key_id, secret))
    if r.status_code in (401, 403):
        raise HiggsfieldError("Clés refusées par Higgsfield : vérifie l'identifiant et le secret sur console.higgsfield.ai.")
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
        raise HiggsfieldError("Crédits Higgsfield épuisés ou trop de demandes : vérifie ton compte sur console.higgsfield.ai.", 402)
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
