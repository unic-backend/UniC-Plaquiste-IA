"""Connecteur LinkedIn (profil perso, et Page entreprise si LinkedIn l'a autorisée).

Flux OAuth 2.0 (code) : le patron crée une appli LinkedIn, colle son Client ID / Secret dans l'appli ; le serveur reçoit le code
sur /api/linkedin/callback, l'échange contre un jeton (60 jours) et le chiffre (secrets_box). Rien n'est publié sans que le patron
touche « Publier » sur un texte qu'il a approuvé. Le jeton, le secret et le code ne sont jamais renvoyés par l'API.
"""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.models import AppSetting

AUTH = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPE_PROFILE = "openid profile w_member_social"
SCOPE_PAGE = SCOPE_PROFILE + " w_organization_social"
STATE_TTL = 600


class LinkedInError(ValueError):
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
        with httpx.Client(timeout=45) as client:
            return client.request(method, url, **kw)
    except httpx.HTTPError:
        raise LinkedInError("Impossible de joindre LinkedIn depuis le serveur. Réessaie dans un instant.", 502)


def status(db: Session, redirect_uri: str = "") -> dict:
    exp = _get(db, "li_expires")
    days = None
    if exp:
        days = max(0, int((float(exp) - time.time()) // 86400))
    connected = bool(_secret(db, "li_token")) and (days is None or days > 0 or float(exp) > time.time())
    return {
        "app_saved": bool(_get(db, "li_client_id") and _get(db, "li_client_secret")),
        "client_id": _get(db, "li_client_id"),
        "connected": connected, "name": _get(db, "li_name"), "days_left": days,
        "page_id": _get(db, "li_org"), "page_scope": _get(db, "li_page_scope") == "1",
        "redirect_uri": redirect_uri,
    }


def save_app(db: Session, client_id: str, client_secret: str, page_id: str = "") -> None:
    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if len(client_id) < 8 or any(c.isspace() for c in client_id):
        raise LinkedInError("Client ID invalide : colle-le sans espace.")
    if client_secret and (len(client_secret) < 8 or any(c.isspace() for c in client_secret)):
        raise LinkedInError("Client Secret invalide : colle-le sans espace.")
    _put(db, "li_client_id", client_id)
    if client_secret:   # vide = on garde l'ancien (le secret n'est jamais réaffiché)
        _put(db, "li_client_secret", secrets_box.encrypt(client_secret))
    if not _secret(db, "li_client_secret"):
        raise LinkedInError("Client Secret manquant.")
    page_id = "".join(ch for ch in (page_id or "") if ch.isdigit())
    _put(db, "li_org", page_id)


def auth_url(db: Session, redirect_uri: str, with_page: bool = False) -> str:
    cid = _get(db, "li_client_id")
    if not cid or not _secret(db, "li_client_secret"):
        raise LinkedInError("Enregistre d'abord le Client ID et le Client Secret.", 409)
    state = secrets.token_urlsafe(24)
    _put(db, "li_state", f"{state}|{int(time.time()) + STATE_TTL}")
    _put(db, "li_page_scope", "1" if with_page else "0")
    q = urlencode({"response_type": "code", "client_id": cid, "redirect_uri": redirect_uri, "state": state,
                   "scope": SCOPE_PAGE if with_page else SCOPE_PROFILE})
    return f"{AUTH}?{q}"


def finish(db: Session, code: str, state: str, redirect_uri: str) -> str:
    """Appelé par la redirection de LinkedIn. Le state est à usage unique et expire (anti-falsification)."""
    saved = _get(db, "li_state")
    _put(db, "li_state", "")
    good, _, until = saved.partition("|")
    if not good or not secrets.compare_digest(good, state or "") or not until.isdigit() or int(until) < time.time():
        raise LinkedInError("Demande expirée ou invalide. Recommence la connexion depuis l'appli.")
    r = _http("POST", TOKEN, data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                   "client_id": _get(db, "li_client_id"), "client_secret": _secret(db, "li_client_secret")},
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code != 200:
        raise LinkedInError("LinkedIn a refusé la connexion (Client ID / Secret ou adresse de retour incorrects).", 400)
    data = r.json()
    token = data.get("access_token", "")
    if not token:
        raise LinkedInError("LinkedIn n'a pas renvoyé de jeton.", 502)
    u = _http("GET", f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {token}"})
    if u.status_code != 200 or not u.json().get("sub"):
        raise LinkedInError("Connexion faite, mais le profil est illisible : ajoute le produit « Sign In with LinkedIn using OpenID Connect » à ton appli.", 400)
    info = u.json()
    _put(db, "li_token", secrets_box.encrypt(token))
    _put(db, "li_expires", str(time.time() + int(data.get("expires_in", 5_184_000))))
    _put(db, "li_person", info["sub"])
    _put(db, "li_name", info.get("name", "") or "")
    return info.get("name", "")


def disconnect(db: Session) -> None:
    for k in ("li_token", "li_expires", "li_person", "li_name", "li_state"):
        _put(db, k, "")


def _explain(r: httpx.Response) -> LinkedInError:
    try:
        msg = (r.json().get("message") or "")[:200]
    except Exception:
        msg = ""
    if r.status_code == 401:
        return LinkedInError("Le jeton LinkedIn a expiré : reconnecte-toi (Paramètres → LinkedIn).", 401)
    if r.status_code == 403:
        return LinkedInError("LinkedIn refuse la publication : ajoute le produit « Share on LinkedIn » à ton appli (ou, pour la Page, "
                             f"l'accès « Community Management »). {msg}".strip(), 403)
    if r.status_code == 422 or r.status_code == 409:
        return LinkedInError(f"LinkedIn refuse ce texte (doublon ou contenu invalide). {msg}".strip(), 422)
    if r.status_code == 429:
        return LinkedInError("Limite LinkedIn atteinte. Réessaie plus tard.", 429)
    return LinkedInError(f"LinkedIn a refusé la publication. {msg}".strip(), 502)


def publish(db: Session, text: str, photo: bytes | None = None, target: str = "profile") -> dict:
    token = _secret(db, "li_token")
    if not token:
        raise LinkedInError("LinkedIn n'est pas connecté.", 409)
    exp = _get(db, "li_expires")
    if exp and float(exp) < time.time():
        raise LinkedInError("Le jeton LinkedIn a expiré : reconnecte-toi (Paramètres → LinkedIn).", 401)
    if target == "page":
        org = _get(db, "li_org")
        if not org or _get(db, "li_page_scope") != "1":
            raise LinkedInError("Page non connectée : enregistre l'identifiant de la Page et reconnecte-toi en mode Page.", 409)
        author = f"urn:li:organization:{org}"
    else:
        author = f"urn:li:person:{_get(db, 'li_person')}"
    text = (text or "").strip()
    if not text:
        raise LinkedInError("Texte vide.")
    h = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0"}
    media, category = [], "NONE"
    if photo:
        reg = _http("POST", f"{API}/v2/assets?action=registerUpload", headers=h, json={"registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"], "owner": author,
            "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]}})
        if reg.status_code not in (200, 201):
            raise _explain(reg)
        v = reg.json().get("value", {})
        up = v.get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")
        asset = v.get("asset")
        if not up or not asset:
            raise LinkedInError("LinkedIn n'a pas accepté la photo.", 502)
        put = _http("PUT", up, headers={"Authorization": f"Bearer {token}"}, content=photo)
        if put.status_code not in (200, 201):
            raise LinkedInError("Envoi de la photo à LinkedIn échoué. Rien n'a été publié.", 502)
        media, category = [{"status": "READY", "media": asset}], "IMAGE"
    body = {"author": author, "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text}, "shareMediaCategory": category, **({"media": media} if media else {})}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
    r = _http("POST", f"{API}/v2/ugcPosts", headers={**h, "Content-Type": "application/json"}, json=body)
    if r.status_code not in (200, 201):
        raise _explain(r)
    urn = r.headers.get("x-restli-id") or r.json().get("id", "")
    return {"id": urn, "url": f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""}
