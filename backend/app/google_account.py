"""Fiche Google du patron, connectée depuis l'appli : identifiant client + secret client + jeton d'actualisation (OAuth).

Les identifiants sont testés auprès de Google AVANT d'être gardés, puis chiffrés (secrets_box) ; jamais renvoyés par l'API ni journalisés.
Le compte et la fiche sont retrouvés automatiquement. Chaque publication ou réponse exige toujours l'approbation du patron.
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app import google_business as gb, secrets_box
from app.models import AppSetting

ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
_SECRET_KEYS = {"gbp_client_id", "gbp_client_secret", "gbp_refresh_token"}   # chiffrés
_PLAIN_KEYS = {"gbp_account_id", "gbp_location_id", "gbp_title"}
_MAP = {"gbp_client_id": "google_client_id", "gbp_client_secret": "google_client_secret", "gbp_refresh_token": "google_refresh_token",
        "gbp_account_id": "gbp_account_id", "gbp_location_id": "gbp_location_id"}


class GoogleAccountError(ValueError):
    pass


def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _discover(client_id: str, client_secret: str, refresh_token: str) -> tuple[str, str, str]:
    """Teste les identifiants (jeton d'accès) puis retrouve le compte et la fiche. Messages lisibles, jamais de secret."""
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.post(gb.TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                           "refresh_token": refresh_token, "grant_type": "refresh_token"})
            if r.status_code != 200:
                raise GoogleAccountError("Google refuse ces identifiants. Vérifie l'identifiant client, le secret client et le jeton "
                                         "(le jeton doit venir de CES identifiants, avec la portée business.manage).")
            head = {"Authorization": f"Bearer {r.json()['access_token']}"}
            acc = c.get(ACCOUNTS, headers=head)
            if acc.status_code in (401, 403):
                raise GoogleAccountError("Google refuse l'accès aux comptes : active les API « My Business Account Management » et "
                                         "« My Business Business Information » dans le projet Google Cloud approuvé.")
            if acc.status_code == 429:
                raise GoogleAccountError("Quota Google dépassé : réessaie dans une minute.")
            if acc.status_code != 200:
                raise GoogleAccountError(f"Google a répondu {acc.status_code} en cherchant ton compte.")
            accounts = acc.json().get("accounts") or []
            if not accounts:
                raise GoogleAccountError("Aucun compte Business Profile sur ce compte Google : connecte-toi avec le compte propriétaire de la fiche.")
            # un compte Google peut avoir plusieurs « comptes » Business Profile (personnel, groupes) : la fiche est dans l'un d'eux
            for account in accounts:
                account_id = account["name"].split("/")[-1]
                loc = c.get(f"{INFO}/accounts/{account_id}/locations", headers=head, params={"readMask": "name,title", "pageSize": 10})
                if loc.status_code == 429:
                    raise GoogleAccountError("Quota Google dépassé : réessaie dans une minute.")
                if loc.status_code != 200:
                    continue
                locations = loc.json().get("locations") or []
                if locations:
                    return account_id, locations[0]["name"].split("/")[-1], str(locations[0].get("title", ""))[:120]
            raise GoogleAccountError(f"Google voit {len(accounts)} compte(s) Business Profile pour ce Google, mais aucune fiche dedans. "
                                     "Refais l'autorisation (Playground) en choisissant le compte Google PROPRIÉTAIRE de la fiche.")
    except GoogleAccountError:   # (sous-classe de ValueError) : ses messages lisibles passent tels quels
        raise
    except httpx.HTTPError:
        raise GoogleAccountError("Impossible de joindre Google depuis le serveur. Réessaie dans un instant.")
    except (KeyError, ValueError):
        raise GoogleAccountError("Réponse inattendue de Google : réessaie.")


def connect(db: Session, client_id: str, client_secret: str, refresh_token: str) -> dict:
    client_id, client_secret, refresh_token = (client_id or "").strip(), (client_secret or "").strip(), (refresh_token or "").strip()
    if not (client_id.endswith(".apps.googleusercontent.com") and len(client_id) > 30):
        raise GoogleAccountError("L'identifiant client finit par « .apps.googleusercontent.com » : recopie-le en entier.")
    if len(client_secret) < 10 or len(refresh_token) < 20:
        raise GoogleAccountError("Secret client ou jeton trop court : recopie-les en entier.")
    account_id, location_id, title = _discover(client_id, client_secret, refresh_token)
    for key, val in (("gbp_client_id", client_id), ("gbp_client_secret", client_secret), ("gbp_refresh_token", refresh_token)):
        _put(db, key, secrets_box.encrypt(val))
    _put(db, "gbp_account_id", account_id)
    _put(db, "gbp_location_id", location_id)
    _put(db, "gbp_title", title)
    db.commit()
    load_into_runtime(db)
    return status(db)


def disconnect(db: Session) -> dict:
    for key in _SECRET_KEYS | _PLAIN_KEYS:
        row = db.get(AppSetting, key)
        if row:
            db.delete(row)
    db.commit()
    gb.set_runtime(None)
    return status(db)


def load_into_runtime(db: Session) -> None:
    values = {}
    for key, name in _MAP.items():
        raw = _get(db, key)
        values[name] = ((secrets_box.decrypt(raw) or "") if raw else "") if key in _SECRET_KEYS else raw
    gb.set_runtime(values if all(values.values()) else None)


def status(db: Session) -> dict:
    secrets = [_get(db, k) for k in sorted(_SECRET_KEYS)]
    saved = any(secrets)
    readable = saved and all(secrets_box.decrypt(s) is not None for s in secrets if s)
    return {"connected": bool(readable and gb.configured()), "title": _get(db, "gbp_title") if readable else "",
            "unreadable": bool(saved and not readable)}
