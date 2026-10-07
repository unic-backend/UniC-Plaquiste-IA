"""Compte Gmail du patron, connecté depuis l'appli : adresse + mot de passe d'application (16 caractères).

Le mot de passe est chiffré (secrets_box), jamais renvoyé par l'API, jamais journalisé. La lecture reste en lecture seule ;
l'envoi exige toujours l'approbation du patron.
"""
from __future__ import annotations

import imaplib
import re
import socket

from sqlalchemy.orm import Session

from app import mailbox, secrets_box
from app.models import AppSetting

GMAIL_IMAP = ("imap.gmail.com", 993)
GMAIL_SMTP = ("smtp.gmail.com", 587)
_ADDR = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailAccountError(ValueError):
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


def clean_password(raw: str) -> str:
    """Google affiche le mot de passe d'application en 4 blocs séparés par des espaces : on les retire."""
    return re.sub(r"\s+", "", raw or "")


def test_login(address: str, password: str) -> None:
    try:
        with imaplib.IMAP4_SSL(*GMAIL_IMAP, timeout=20) as box:
            box.login(address, password)
    except imaplib.IMAP4.error as exc:
        raw = re.sub(r"\s+", " ", str(exc)).strip()[:140]   # réponse de Gmail : jamais le mot de passe
        low = raw.lower()
        if "application-specific" in low or "app password" in low:
            hint = "Google demande un mot de passe d'APPLICATION (pas ton mot de passe Gmail)."
        elif "imap" in low and ("disabled" in low or "not enabled" in low):
            hint = "L'accès IMAP est désactivé dans Gmail (Paramètres › Transfert et POP/IMAP › Activer IMAP)."
        elif "weblogin" in low or "web login" in low:
            hint = "Google demande une confirmation : ouvre l'alerte de sécurité reçue et touche « C'était moi »."
        else:
            hint = ("Gmail refuse la connexion. Causes les plus fréquentes : 1) alerte de sécurité Google à confirmer (« C'était moi ») ; "
                    "2) mot de passe d'application mal recopié : recrée-en un ; 3) IMAP désactivé dans Gmail.")
        raise MailAccountError(f"{hint} (Gmail : {raw})")
    except (socket.timeout, OSError):
        raise MailAccountError("Impossible de joindre Gmail depuis le serveur. Réessaie dans un instant.")


def connect(db: Session, address: str, password: str) -> dict:
    address, password = (address or "").strip().lower(), clean_password(password)
    if not _ADDR.match(address):
        raise MailAccountError("Adresse e-mail invalide.")
    if len(password) != 16 or not password.isalpha():
        raise MailAccountError("Un mot de passe d'application Gmail fait 16 lettres (sans espaces ni chiffres).")
    test_login(address, password)
    _put(db, "mail_address", address)
    _put(db, "mail_secret", secrets_box.encrypt(password))
    db.commit()
    mailbox.set_runtime(address, password)
    return status(db)


def disconnect(db: Session) -> dict:
    for key in ("mail_address", "mail_secret"):
        row = db.get(AppSetting, key)
        if row:
            db.delete(row)
    db.commit()
    mailbox.set_runtime("", "")
    return status(db)


def load_into_runtime(db: Session) -> None:
    address, secret = _get(db, "mail_address"), _get(db, "mail_secret")
    pwd = secrets_box.decrypt(secret) if secret else None
    mailbox.set_runtime(address if pwd else "", pwd or "")


def mask(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}{'•' * max(2, len(local) - 1)}@{domain}" if local else ""


def status(db: Session) -> dict:
    address = _get(db, "mail_address")
    return {"connected": bool(address and _get(db, "mail_secret")), "address": mask(address) if address else ""}
