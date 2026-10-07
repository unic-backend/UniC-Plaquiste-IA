"""Connecteur Instagram (compte professionnel) via « Instagram API with Instagram Login ».

Le patron crée une appli Meta, colle l'ID et le secret de l'appli Instagram ; le serveur reçoit le code sur /api/instagram/callback,
l'échange contre un jeton longue durée (60 jours, prolongé automatiquement) et le chiffre (secrets_box). Instagram exige une
photo accessible par une URL publique : la photo est hébergée sur le serveur sous un nom aléatoire, le temps de la publication,
puis effacée. Rien n'est publié sans que le patron touche « Publier » sur un texte approuvé.
"""
from __future__ import annotations

import io
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app import secrets_box
from app.config import settings
from app.models import AppSetting

AUTH = "https://www.instagram.com/oauth/authorize"
TOKEN = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
VERSION = "v21.0"
SCOPE = "instagram_business_basic,instagram_business_content_publish"
STATE_TTL = 600
REFRESH_BELOW_DAYS = 20
MAX_SIDE = 1440
MEDIA_TTL = 3600


class InstagramError(ValueError):
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


def _secret(db: Session, key: str) -> str:
    raw = _get(db, key)
    return (secrets_box.decrypt(raw) or "") if raw else ""


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=60) as client:
            return client.request(method, url, **kw)
    except httpx.HTTPError:
        raise InstagramError("Impossible de joindre Instagram depuis le serveur. Réessaie dans un instant.", 502)


def _days_left(db: Session) -> int | None:
    exp = _get(db, "ig_expires")
    return max(0, int((float(exp) - time.time()) // 86400)) if exp else None


def status(db: Session, redirect_uri: str = "") -> dict:
    days = _days_left(db)
    return {
        "app_saved": bool(_get(db, "ig_app_id") and _get(db, "ig_app_secret")),
        "app_id": _get(db, "ig_app_id"),
        "connected": bool(_secret(db, "ig_token")) and (days is None or days > 0),
        "username": _get(db, "ig_username"), "days_left": days, "redirect_uri": redirect_uri,
    }


def save_app(db: Session, app_id: str, app_secret: str) -> None:
    app_id, app_secret = (app_id or "").strip(), (app_secret or "").strip()
    if not app_id.isdigit() or len(app_id) < 8:
        raise InstagramError("ID de l'appli Instagram invalide : des chiffres seulement (copié dans Meta → Instagram → API setup).")
    if app_secret and (len(app_secret) < 16 or any(c.isspace() for c in app_secret)):
        raise InstagramError("Secret invalide : colle-le sans espace.")
    _put(db, "ig_app_id", app_id)
    if app_secret:
        _put(db, "ig_app_secret", secrets_box.encrypt(app_secret))
    if not _secret(db, "ig_app_secret"):
        raise InstagramError("Secret de l'appli manquant.")


def auth_url(db: Session, redirect_uri: str) -> str:
    app_id = _get(db, "ig_app_id")
    if not app_id or not _secret(db, "ig_app_secret"):
        raise InstagramError("Enregistre d'abord l'ID et le secret de l'appli Instagram.", 409)
    state = secrets.token_urlsafe(24)
    _put(db, "ig_state", f"{state}|{int(time.time()) + STATE_TTL}")
    q = urlencode({"client_id": app_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE, "state": state,
                   "enable_fb_login": "0", "force_authentication": "1"})
    return f"{AUTH}?{q}"


def finish(db: Session, code: str, state: str, redirect_uri: str) -> str:
    """Retour d'Instagram. Le state est à usage unique et expire (anti-falsification)."""
    saved = _get(db, "ig_state")
    _put(db, "ig_state", "")
    good, _, until = saved.partition("|")
    if not good or not secrets.compare_digest(good, state or "") or not until.isdigit() or int(until) < time.time():
        raise InstagramError("Demande expirée ou invalide. Recommence la connexion depuis l'appli.")
    code = (code or "").split("#_")[0]   # Instagram ajoute parfois « #_ » au code
    r = _http("POST", TOKEN, data={"client_id": _get(db, "ig_app_id"), "client_secret": _secret(db, "ig_app_secret"),
                                   "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code})
    if r.status_code != 200:
        raise InstagramError("Instagram a refusé la connexion (ID / secret de l'appli ou adresse de retour incorrects).")
    data = r.json()
    if isinstance(data.get("data"), list) and data["data"]:
        data = data["data"][0]
    short = data.get("access_token", "")
    if not short:
        raise InstagramError("Instagram n'a pas renvoyé de jeton.", 502)
    lg = _http("GET", f"{GRAPH}/access_token", params={"grant_type": "ig_exchange_token",
                                                        "client_secret": _secret(db, "ig_app_secret"), "access_token": short})
    if lg.status_code != 200 or not lg.json().get("access_token"):
        raise InstagramError("Impossible d'obtenir le jeton longue durée d'Instagram.", 502)
    token, ttl = lg.json()["access_token"], int(lg.json().get("expires_in", 5_184_000))
    me = _http("GET", f"{GRAPH}/{VERSION}/me", params={"fields": "user_id,username,account_type", "access_token": token})
    if me.status_code != 200:
        raise InstagramError("Connexion faite, mais le compte est illisible. Le compte doit être professionnel (Business ou Créateur).")
    info = me.json()
    ig_id = str(info.get("user_id") or info.get("id") or data.get("user_id") or "")
    if not ig_id:
        raise InstagramError("Identifiant du compte Instagram introuvable.", 502)
    _put(db, "ig_token", secrets_box.encrypt(token))
    _put(db, "ig_expires", str(time.time() + ttl))
    _put(db, "ig_user_id", ig_id)
    _put(db, "ig_username", info.get("username", "") or "")
    return info.get("username", "")


def disconnect(db: Session) -> None:
    for k in ("ig_token", "ig_expires", "ig_user_id", "ig_username", "ig_state"):
        _put(db, k, "")


def refresh_if_needed(db: Session) -> None:
    """Prolonge le jeton de 60 jours quand il approche de la fin (Instagram l'autorise après 24 h d'âge)."""
    days = _days_left(db)
    token = _secret(db, "ig_token")
    if not token or days is None or days > REFRESH_BELOW_DAYS:
        return
    r = _http("GET", f"{GRAPH}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token})
    if r.status_code == 200 and r.json().get("access_token"):
        _put(db, "ig_token", secrets_box.encrypt(r.json()["access_token"]))
        _put(db, "ig_expires", str(time.time() + int(r.json().get("expires_in", 5_184_000))))


# ---------- photo hébergée le temps de la publication ----------

def _media_dir() -> Path:
    p = settings.storage_path / "ig_public"
    p.mkdir(parents=True, exist_ok=True)
    return p


def prepare_photo(raw: bytes) -> bytes:
    """JPEG propre pour Instagram : orientation corrigée, 1440 px maximum, format entre 4:5 et 1,91:1 (recadrage centré si besoin)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception:
        raise InstagramError("Photo illisible : envoie une image JPEG ou PNG.")
    w, h = img.size
    ratio = w / h
    if ratio < 0.8:      # trop haute : on recadre au format 4:5
        nh = int(w / 0.8)
        top = (h - nh) // 2
        img = img.crop((0, top, w, top + nh))
    elif ratio > 1.91:   # trop large : on recadre à 1,91:1
        nw = int(h * 1.91)
        left = (w - nw) // 2
        img = img.crop((left, 0, left + nw, h))
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def host_photo(jpeg: bytes) -> str:
    for old in _media_dir().glob("*.jpg"):   # ménage : rien ne reste plus d'une heure
        if time.time() - old.stat().st_mtime > MEDIA_TTL:
            old.unlink(missing_ok=True)
    token = secrets.token_urlsafe(24)
    (_media_dir() / f"{token}.jpg").write_bytes(jpeg)
    return token


def photo_path(token: str) -> Path | None:
    if not token or not all(c.isalnum() or c in "-_" for c in token):
        return None
    p = _media_dir() / f"{token}.jpg"
    return p if p.is_file() else None


def _explain(r: httpx.Response) -> InstagramError:
    try:
        err = r.json().get("error", {})
        msg = (err.get("message") or "")[:220]
        code = err.get("code")
    except Exception:
        msg, code = "", None
    if r.status_code == 401 or code in (190, 102):
        return InstagramError("Le jeton Instagram a expiré : reconnecte-toi (Paramètres → Instagram).", 401)
    if code in (10, 200, 3) or r.status_code == 403:
        return InstagramError(f"Instagram refuse la publication : vérifie que le compte est professionnel et ajouté comme testeur de l'appli. {msg}".strip(), 403)
    if code == 9004 or code == 9007 or "media" in msg.lower():
        return InstagramError(f"Instagram n'a pas pu lire la photo ou le texte. {msg}".strip(), 422)
    if code in (4, 17, 32, 613) or r.status_code == 429:
        return InstagramError("Limite Instagram atteinte. Réessaie plus tard.", 429)
    return InstagramError(f"Instagram a refusé la publication. {msg}".strip(), 502)


def publish(db: Session, caption: str, image_url: str) -> dict:
    refresh_if_needed(db)
    token = _secret(db, "ig_token")
    ig_id = _get(db, "ig_user_id")
    if not token or not ig_id:
        raise InstagramError("Instagram n'est pas connecté.", 409)
    days = _days_left(db)
    if days is not None and days <= 0:
        raise InstagramError("Le jeton Instagram a expiré : reconnecte-toi (Paramètres → Instagram).", 401)
    caption = (caption or "").strip()
    if not caption:
        raise InstagramError("Texte vide.")
    c = _http("POST", f"{GRAPH}/{VERSION}/{ig_id}/media", data={"image_url": image_url, "caption": caption, "access_token": token})
    if c.status_code != 200 or not c.json().get("id"):
        raise _explain(c)
    cid = c.json()["id"]
    for _ in range(8):   # le conteneur doit être prêt avant la publication
        s = _http("GET", f"{GRAPH}/{VERSION}/{cid}", params={"fields": "status_code", "access_token": token})
        st = s.json().get("status_code") if s.status_code == 200 else None
        if st == "FINISHED" or st is None:
            break
        if st in ("ERROR", "EXPIRED"):
            raise InstagramError("Instagram a refusé la photo (format ou taille). Essaie une autre photo.", 422)
        time.sleep(1.5)
    p = _http("POST", f"{GRAPH}/{VERSION}/{ig_id}/media_publish", data={"creation_id": cid, "access_token": token})
    if p.status_code != 200 or not p.json().get("id"):
        raise _explain(p)
    mid = p.json()["id"]
    link = _http("GET", f"{GRAPH}/{VERSION}/{mid}", params={"fields": "permalink", "access_token": token})
    url = link.json().get("permalink", "") if link.status_code == 200 else ""
    return {"id": mid, "url": url}
