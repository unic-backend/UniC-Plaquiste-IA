"""Connexion du patron : e-mail + mot de passe de son choix, en plus du code d'accès (gardé pour secours).

- Mot de passe : scrypt salé (jamais stocké en clair). Jeton de session aléatoire par appareil, seul son SHA-256 est gardé.
- Le jeton passe dans le même en-tête que le code d'accès (X-Access-Code) : toute l'appli fonctionne sans changement.
- Mot de passe oublié : on se reconnecte avec le code d'accès (Render), puis on choisit un nouveau mot de passe.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AuthSession, User

TOKEN_PREFIX = "uat_"
SESSION_DAYS = 365
MIN_PASSWORD = 8
_cache: dict[str, float] = {}      # empreinte -> fin de validité en cache (évite une lecture de base par requête)
CACHE_SECONDS = 300


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _owner(db: Session) -> User | None:
    return db.query(User).filter(User.is_active.is_(True)).order_by(User.created_at).first()


def account_ready(db: Session) -> bool:
    u = _owner(db)
    return bool(u and (u.password_hash or "").startswith("scrypt$"))


def _valid_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email):
        raise AuthError("Adresse e-mail invalide.")
    return email


def set_account(db: Session, email: str, password: str, current_password: str | None, by_access_code: bool) -> None:
    """Crée ou change l'e-mail et le mot de passe. Avec un jeton (pas le code d'accès), l'ancien mot de passe est exigé."""
    u = _owner(db)
    if u is None:
        raise AuthError("Compte propriétaire introuvable.")
    if account_ready(db) and not by_access_code and not verify_password(current_password or "", u.password_hash):
        raise AuthError("Mot de passe actuel incorrect.")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Mot de passe trop court : {MIN_PASSWORD} caractères minimum.")
    u.email = _valid_email(email)
    u.password_hash = hash_password(password)
    db.query(AuthSession).delete()   # nouveau mot de passe : les anciens appareils doivent se reconnecter
    _cache.clear()
    db.flush()


def login(db: Session, email: str, password: str, device: str = "") -> str:
    u = _owner(db)
    ok = u is not None and account_ready(db) and (u.email or "").lower() == (email or "").strip().lower() \
        and verify_password(password or "", u.password_hash)
    if not ok:
        time.sleep(0.4)   # ralentit les essais à la chaîne
        raise AuthError("E-mail ou mot de passe incorrect.")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), device=(device or "")[:120],
                       created_at=now, last_used=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    u.last_login = now
    db.flush()
    return token


def token_valid(db: Session, token: str) -> bool:
    if not token or not token.startswith(TOKEN_PREFIX):
        return False
    h = hashlib.sha256(token.encode()).hexdigest()
    if _cache.get(h, 0) > time.time():
        return True
    row = db.query(AuthSession).filter(AuthSession.token_hash == h).first()
    if row is None:
        return False
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return False
    # lecture seule : aucune écriture ici (une conversation en cours peut tenir l'écriture de la base)
    _cache[h] = time.time() + CACHE_SECONDS
    return True


def touch(db: Session, token: str) -> None:
    """Session glissante : prolongée à l'ouverture de l'appli (route /auth/me), pas à chaque requête."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return
    row = db.query(AuthSession).filter(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()).first()
    if row is not None:
        now = datetime.now(timezone.utc)
        row.last_used, row.expires_at = now, now + timedelta(days=SESSION_DAYS)
        db.flush()


def logout(db: Session, token: str) -> None:
    if token and token.startswith(TOKEN_PREFIX):
        h = hashlib.sha256(token.encode()).hexdigest()
        db.query(AuthSession).filter(AuthSession.token_hash == h).delete()
        _cache.pop(h, None)
        db.flush()


def devices(db: Session) -> list[dict]:
    return [{"device": r.device or "Appareil", "last_used": r.last_used.isoformat() if r.last_used else None}
            for r in db.query(AuthSession).order_by(AuthSession.last_used.desc()).all()]
