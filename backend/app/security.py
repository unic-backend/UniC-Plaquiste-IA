from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


def hash_password(password: str) -> str:
    # Usage solo : pas de connexion. Hash aléatoire inutilisable.
    return "disabled$" + secrets.token_hex(16)


def get_current_user(db: Session = Depends(get_db)) -> User:
    """Application mono-utilisateur : toujours le propriétaire."""
    user = db.query(User).filter(User.is_active.is_(True)).order_by(User.created_at).first()
    if user is None:
        raise HTTPException(status_code=503, detail="Propriétaire introuvable")
    return user


def require_roles(*roles: str):
    return get_current_user
