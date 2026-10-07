"""Coffre pour les secrets enregistrés depuis l'appli (mot de passe d'application Gmail…).

Chiffrement Fernet. Clé : dérivée de UNIC_SECRET_KEY (Render) si présente, sinon un fichier `.secret_key` créé sur le disque
persistant (droits 0600). Limite honnête : sans UNIC_SECRET_KEY, la clé vit sur le même disque que la base : cela protège
une copie de la base seule, pas un accès complet au serveur.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _key() -> bytes:
    env = os.environ.get("UNIC_SECRET_KEY", "").strip()
    if env:   # n'importe quelle chaîne : on en dérive une clé Fernet valide
        return base64.urlsafe_b64encode(hashlib.sha256(b"unic-secrets-box|" + env.encode()).digest())
    path = Path(settings.data_path) / ".secret_key"
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_bytes().strip()


def encrypt(text: str) -> str:
    return Fernet(_key()).encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return Fernet(_key()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
