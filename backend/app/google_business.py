"""Fiche Google (Business Profile) : profil, avis, réponses, actualités.

Authentification : OAuth2 avec un refresh token (usage mono-propriétaire).
Rien n'est lu ni publié sans configuration complète. Les secrets ne sont
jamais renvoyés ni journalisés.
"""
from __future__ import annotations

import re
import time

import httpx

from app.config import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
V4 = "https://mybusiness.googleapis.com/v4"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
TIMEOUT = 20.0

_STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{4,200}$")

_token_cache: dict = {"value": "", "exp": 0.0}


class GoogleError(Exception):
    """Erreur lisible, sans secret."""


def configured() -> bool:
    return all([settings.google_client_id, settings.google_client_secret, settings.google_refresh_token,
                settings.gbp_account_id, settings.gbp_location_id])


def missing_settings() -> list[str]:
    names = {
        "GOOGLE_CLIENT_ID": settings.google_client_id, "GOOGLE_CLIENT_SECRET": settings.google_client_secret,
        "GOOGLE_REFRESH_TOKEN": settings.google_refresh_token, "GBP_ACCOUNT_ID": settings.gbp_account_id,
        "GBP_LOCATION_ID": settings.gbp_location_id,
    }
    return [k for k, v in names.items() if not v]


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


def _access_token(client: httpx.Client) -> str:
    if _token_cache["value"] and _token_cache["exp"] > time.time() + 60:
        return _token_cache["value"]
    r = client.post(TOKEN_URL, data={
        "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "refresh_token": settings.google_refresh_token, "grant_type": "refresh_token",
    })
    if r.status_code != 200:
        raise GoogleError("Google a refusé l'authentification. Régénérez le refresh token.")
    data = r.json()
    _token_cache["value"] = data["access_token"]
    _token_cache["exp"] = time.time() + int(data.get("expires_in", 3000))
    return _token_cache["value"]


def _call(method: str, url: str, **kw) -> dict:
    if not configured():
        raise GoogleError("Fiche Google NON DISPONIBLE : configuration incomplète (" + ", ".join(missing_settings()) + ").")
    try:
        with _client() as c:
            token = _access_token(c)
            r = c.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)
    except httpx.HTTPError as exc:
        raise GoogleError(f"Google injoignable ({type(exc).__name__}).") from exc
    if r.status_code in (401, 403):
        _token_cache["value"] = ""
        raise GoogleError(
            "Accès refusé par Google (droits ou API Business Profile non approuvée pour ce projet)."
        )
    if r.status_code == 429:
        raise GoogleError("Quota Google dépassé. Réessayez plus tard.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        raise GoogleError(f"Google a répondu {r.status_code}. {msg[:200]}")
    return r.json() if r.content else {}


def _loc_path() -> str:
    return f"accounts/{settings.gbp_account_id}/locations/{settings.gbp_location_id}"


def get_location() -> dict:
    data = _call("GET", f"{INFO}/locations/{settings.gbp_location_id}", params={
        "readMask": "title,phoneNumbers,websiteUri,regularHours,categories,profile,storefrontAddress"})
    return data


def audit_location(loc: dict) -> dict:
    """Lacunes de la fiche, calculées sur les données réelles (aucune invention)."""
    gaps: list[str] = []
    if not (loc.get("websiteUri") or "").strip():
        gaps.append("Site web non renseigné")
    if not (loc.get("phoneNumbers") or {}).get("primaryPhone"):
        gaps.append("Téléphone non renseigné")
    if not (loc.get("regularHours") or {}).get("periods"):
        gaps.append("Horaires d'ouverture non renseignés")
    if not (loc.get("categories") or {}).get("primaryCategory"):
        gaps.append("Catégorie principale absente")
    elif not (loc.get("categories") or {}).get("additionalCategories"):
        gaps.append("Aucune catégorie secondaire (ex. plâtrier, peintre)")
    desc = ((loc.get("profile") or {}).get("description") or "").strip()
    if len(desc) < 250:
        gaps.append("Description absente ou courte (visez 250+ caractères avec métier + ville)")
    if not loc.get("storefrontAddress"):
        gaps.append("Adresse / zone de service non renseignée")
    return {
        "title": loc.get("title", ""), "website": loc.get("websiteUri", ""),
        "phone": (loc.get("phoneNumbers") or {}).get("primaryPhone", ""),
        "description": desc, "gaps": gaps, "complete": not gaps,
    }


def list_reviews(page_size: int = 20) -> list[dict]:
    data = _call("GET", f"{V4}/{_loc_path()}/reviews", params={"pageSize": max(1, min(page_size, 50))})
    out = []
    for r in data.get("reviews", []):
        out.append({
            "id": r.get("reviewId", ""),
            "author": (r.get("reviewer") or {}).get("displayName", "Anonyme"),
            "stars": _STARS.get(r.get("starRating", ""), 0),
            "comment": r.get("comment", ""),
            "created": r.get("createTime", ""),
            "replied": bool(r.get("reviewReply")),
        })
    return out


def reply_review(review_id: str, comment: str) -> None:
    if not REVIEW_ID_RE.match(review_id):
        raise GoogleError("Identifiant d'avis invalide.")
    _call("PUT", f"{V4}/{_loc_path()}/reviews/{review_id}/reply", json={"comment": comment[:4000]})


def create_post(summary: str, link: str = "") -> str:
    """Actualité standard sur la fiche. Rend le nom de ressource du post créé."""
    body: dict = {"languageCode": "fr", "summary": summary[:1500], "topicType": "STANDARD"}
    if link.lower().startswith(("http://", "https://")):
        body["callToAction"] = {"actionType": "LEARN_MORE", "url": link}
    data = _call("POST", f"{V4}/{_loc_path()}/localPosts", json=body)
    return data.get("name", "")
