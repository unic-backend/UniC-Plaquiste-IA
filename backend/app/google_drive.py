"""Google Drive du patron : rangement des devis et factures, copie de la sauvegarde du jour, lecture des photos de chantier.

- Même compte Google que la fiche (identifiants chiffrés par `google_account`, jeton partagé avec `google_business`).
  Le jeton doit aussi porter les portées Drive : `drive.file` (déposer) et `drive.readonly` (lire les photos).
- Chaque usage est un réglage coupé par défaut : l'allumer est le clic du patron. Les fichiers vont dans SON Drive, dossier « UniC IA ».
- Rien n'est jamais supprimé dans le Drive : un document refait remplace le contenu du fichier du même nom (pas de doublon).
- Un dépôt raté ne bloque jamais un devis ni une sauvegarde : l'erreur est gardée pour l'écran de réglages.
- Les noms et contenus lus dans le Drive sont des données, jamais des consignes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app import google_business as gb
from app.models import AppSetting

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT = "UniC IA"
OPTIONS = {   # réglage -> libellé (tous coupés par défaut)
    "drive_docs": "Ranger chaque devis et facture (PDF) dans le Drive, par client",
    "drive_backup": "Copier la sauvegarde du jour dans le Drive",
    "drive_photos": "Laisser l'assistant lire les photos de chantier du Drive",
}
SCOPE_HELP = ("Refais l'autorisation Google en ajoutant les portées Drive « drive.file » et « drive.readonly », "
              "puis recolle le nouveau jeton dans Paramètres › Google.")
_state: dict = {"last_ok": "", "last_error": ""}
_folders: dict[tuple[str, str], str] = {}   # (parent, nom) -> id : évite de rechercher le même dossier à chaque dépôt
_lock = threading.Lock()


class DriveError(Exception):
    """Erreur lisible, sans secret."""


def available() -> bool:
    """Identifiants Google présents (ceux de la fiche) : le Drive n'en demande pas d'autres."""
    return all(gb._v(k) for k in ("google_client_id", "google_client_secret", "google_refresh_token"))


def enabled(db: Session, key: str) -> bool:
    row = db.get(AppSetting, key)
    return bool(row and row.value == "1")


def status(db: Session) -> dict:
    return {"available": available(), "options": {k: enabled(db, k) for k in OPTIONS}, "labels": OPTIONS,
            "folder": ROOT, "last_ok": _state["last_ok"], "last_error": _state["last_error"]}


def set_options(db: Session, values: dict) -> dict:
    for key, on in values.items():
        if key not in OPTIONS:
            continue
        row = db.get(AppSetting, key)
        if row:
            row.value = "1" if on else "0"
        else:
            db.add(AppSetting(key=key, value="1" if on else "0"))
    db.commit()
    return status(db)


def _q(text: str) -> str:
    """Valeur entre apostrophes dans une requête Drive."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _clean(name: str) -> str:
    name = re.sub(r"[\\/\x00-\x1f]+", " ", name or "").strip()
    return name[:120] or "Sans nom"


def _call(c: httpx.Client, method: str, url: str, **kw) -> dict:
    head = {**kw.pop("headers", {}), "Authorization": f"Bearer {gb._access_token(c)}"}
    try:
        r = c.request(method, url, headers=head, **kw)
    except httpx.HTTPError as exc:
        raise DriveError(f"Google Drive injoignable ({type(exc).__name__}).") from exc
    if r.status_code in (401, 403):
        gb._token_cache["value"] = ""
        raise DriveError("Google Drive refuse l'accès. " + SCOPE_HELP)
    if r.status_code == 429:
        raise DriveError("Quota Google Drive dépassé : nouvel essai au prochain document.")
    if r.status_code >= 400:
        raise DriveError(f"Google Drive a répondu {r.status_code}.")
    return r.json() if r.content else {}


def _folder(c: httpx.Client, name: str, parent: str) -> str:
    key = (parent, name)
    if key in _folders:
        return _folders[key]
    q = f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and '{_q(parent)}' in parents and trashed = false"
    found = _call(c, "GET", API, params={"q": q, "fields": "files(id)", "pageSize": 1}).get("files") or []
    fid = found[0]["id"] if found else _call(c, "POST", API, params={"fields": "id"},
                                             json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]})["id"]
    _folders[key] = fid
    return fid


def upload(data: bytes, parts: list[str], name: str, mime: str = "application/pdf") -> str:
    """Dépose `data` dans « UniC IA/<parts…>/<name> ». Même nom déjà là : contenu remplacé, pas de doublon. Rend l'id du fichier."""
    if not available():
        raise DriveError("Compte Google non connecté : Paramètres › Google.")
    name = _clean(name)
    try:
        return _upload(data, parts, name, mime)
    except DriveError:
        _folders.clear()   # dossier déplacé ou supprimé à la main dans le Drive : on le recherche au prochain dépôt
        raise


def _upload(data: bytes, parts: list[str], name: str, mime: str) -> str:
    with _lock, httpx.Client(timeout=60.0) as c:
        parent = _folder(c, ROOT, "root")
        for p in parts:
            parent = _folder(c, _clean(p), parent)
        q = f"name = '{_q(name)}' and '{_q(parent)}' in parents and trashed = false"
        same = _call(c, "GET", API, params={"q": q, "fields": "files(id)", "pageSize": 1}).get("files") or []
        if same:
            fid = same[0]["id"]
            _call(c, "PATCH", f"{UPLOAD}/{fid}", params={"uploadType": "media", "fields": "id"}, content=data,
                  headers={"Content-Type": mime})
            return fid
        boundary = "unic-drive-" + os.urandom(8).hex()
        meta = json.dumps({"name": name, "parents": [parent]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
                + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode() + data + f"\r\n--{boundary}--".encode())
        out = _call(c, "POST", UPLOAD, params={"uploadType": "multipart", "fields": "id"}, content=body,
                    headers={"Content-Type": f"multipart/related; boundary={boundary}"})
        return out["id"]


def _run(fn, *args) -> None:
    """Dépôt en arrière-plan (tests : tout de suite). Jamais d'exception : le devis ou la sauvegarde continue."""
    def job():
        try:
            fn(*args)
            _state["last_ok"], _state["last_error"] = datetime.now(timezone.utc).isoformat(), ""
        except DriveError as exc:
            _state["last_error"] = str(exc)[:300]
        except Exception as exc:   # un dépôt raté ne doit jamais casser le serveur
            logger.exception("Dépôt Google Drive impossible")
            _state["last_error"] = f"{type(exc).__name__}"[:300]
    if os.environ.get("UNIC_NO_BACKGROUND"):
        job()
    else:
        threading.Thread(target=job, daemon=True, name="unic-drive").start()


def push_document(db: Session, path: Path, kind: str, client: str, filename: str) -> bool:
    """Devis/facture -> « UniC IA/Devis|Factures/<client>/ ». Rend False si l'option est coupée ou Google absent."""
    if not (available() and enabled(db, "drive_docs")):
        return False
    folder = "Devis" if kind == "quotation" else "Factures"
    _run(lambda: upload(Path(path).read_bytes(), [folder, client or "Sans client"], filename))
    return True


def push_backup(db: Session, data: bytes, filename: str) -> bool:
    """Sauvegarde du jour (déjà chiffrée si un mot de passe est réglé) -> « UniC IA/Sauvegardes/ »."""
    if not (available() and enabled(db, "drive_backup")):
        return False
    _run(lambda: upload(data, ["Sauvegardes"], filename, mime="application/zip"))
    return True


def list_photos(db: Session, folder: str = "", limit: int = 30) -> list[dict]:
    """Photos d'un dossier du Drive (nom cherché, ex. « Cloisons ») ou les plus récentes. Lecture seule."""
    if not enabled(db, "drive_photos"):
        raise DriveError("Lecture des photos coupée : Paramètres › Google Drive.")
    if not available():
        raise DriveError("Compte Google non connecté : Paramètres › Google.")
    limit = max(1, min(int(limit or 30), 100))
    q = "mimeType contains 'image/' and trashed = false"
    with httpx.Client(timeout=30.0) as c:
        if folder.strip():
            fq = f"mimeType = '{FOLDER_MIME}' and name contains '{_q(folder.strip()[:80])}' and trashed = false"
            dirs = _call(c, "GET", API, params={"q": fq, "fields": "files(id)", "pageSize": 10}).get("files") or []
            if not dirs:
                return []
            q += " and (" + " or ".join(f"'{_q(d['id'])}' in parents" for d in dirs) + ")"
        files = _call(c, "GET", API, params={"q": q, "pageSize": limit, "orderBy": "createdTime desc",
                                              "fields": "files(id,name,createdTime,webViewLink,thumbnailLink)"}).get("files") or []
    return [{"id": f.get("id", ""), "name": str(f.get("name", ""))[:160], "date": f.get("createdTime", ""),
             "lien": f.get("webViewLink", ""), "miniature": f.get("thumbnailLink", "")} for f in files]
