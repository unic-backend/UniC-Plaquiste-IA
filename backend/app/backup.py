"""Sauvegardes : base complète (devis, factures, clients, mémoire…) + signature, chaque jour, gardées ici ET hors du serveur.

- Copie cohérente de la base SQLite (API de sauvegarde SQLite, même pendant l'utilisation), compressée en .zip.
- Hors serveur : déposée dans ta boîte Gmail, dossier « UniC-Sauvegardes » (IMAP APPEND, rien n'est envoyé à un tiers).
- Jamais dans l'archive : la clé de chiffrement des secrets (.secret_key). Après une perte du disque, les connecteurs
  (Gmail, LinkedIn, site, voix) se reconnectent ; tout le reste revient.
- Restauration : une sauvegarde de sécurité de l'état actuel est faite juste avant.
"""
from __future__ import annotations

import imaplib
import io
import json
import logging
import sqlite3
import threading
import time
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app import mailbox
from app.config import settings

logger = logging.getLogger("unic.backup")

PREFIX = "UniC_Sauvegarde_"
KEEP_LOCAL = 14
KEEP_REMOTE = 30
REMOTE_FOLDER = "UniC-Sauvegardes"
REMOTE_MAX_MB = 20
EVERY_HOURS = 24
_lock = threading.Lock()


class BackupError(Exception):
    pass


def _db_file() -> Path:
    if not settings.is_sqlite:
        raise BackupError("Sauvegarde automatique prévue pour la base SQLite du serveur.")
    return Path(settings.db_url.split("sqlite:///", 1)[1])


def _signature() -> Path:
    return settings.storage_path / "brand" / "signature.png"


def _status_file() -> Path:
    return settings.backups_path / "status.json"


def status() -> dict:
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_status(**kw) -> None:
    data = status()
    data.update(kw)
    _status_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _snapshot(dest: Path) -> dict:
    """Copie cohérente de la base (même en cours d'écriture) et quelques chiffres pour vérifier la sauvegarde."""
    src = sqlite3.connect(str(_db_file()))
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        src.close()
    counts = {}
    try:
        for table in ("quotations", "invoices", "customers", "memories", "messages", "purchase_orders", "delivery_notes"):
            try:
                counts[table] = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                pass
        if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("Copie de la base corrompue : sauvegarde annulée.")
    finally:
        out.close()
    return counts


def create(reason: str = "manuel") -> dict:
    """Crée une sauvegarde locale (zip). Rend {name, size, counts}."""
    with _lock:
        folder = settings.backups_path
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        name = f"{PREFIX}{stamp}.zip"
        tmp_db = folder / f".{stamp}.db"
        try:
            counts = _snapshot(tmp_db)
            manifest = {"app": "UniC AI", "created_at": datetime.now(timezone.utc).isoformat(), "reason": reason,
                        "counts": counts, "format": 1}
            with zipfile.ZipFile(folder / name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                z.write(tmp_db, "unic.db")
                for f in (_signature(), _signature().with_name("stamp.png")):
                    if f.exists():
                        z.write(f, f"brand/{f.name}")
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        finally:
            tmp_db.unlink(missing_ok=True)
        _prune_local()
        size = (folder / name).stat().st_size
        _save_status(last_local=manifest["created_at"], last_name=name)
        return {"name": name, "size": size, "counts": counts}


def _prune_local() -> None:
    files = sorted(settings.backups_path.glob(f"{PREFIX}*.zip"))
    for old in files[:-KEEP_LOCAL]:
        old.unlink(missing_ok=True)


def list_local() -> list[dict]:
    out = []
    for f in sorted(settings.backups_path.glob(f"{PREFIX}*.zip"), reverse=True):
        out.append({"name": f.name, "size": f.stat().st_size,
                    "created_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()})
    return out


def path_of(name: str) -> Path:
    if not (name.startswith(PREFIX) and name.endswith(".zip")) or "/" in name or ".." in name:
        raise BackupError("Nom de sauvegarde invalide.")
    p = settings.backups_path / name
    if not p.exists():
        raise BackupError("Sauvegarde introuvable.")
    return p


# ---------- hors serveur : boîte Gmail ----------

def offsite_available() -> bool:
    return mailbox.imap_configured()


def push_offsite(name: str) -> dict:
    """Dépose l'archive dans la boîte mail (dossier UniC-Sauvegardes) et ne garde que les 30 dernières là-bas."""
    p = path_of(name)
    if p.stat().st_size > REMOTE_MAX_MB * 1024 * 1024:
        raise BackupError(f"Sauvegarde trop lourde pour la boîte mail (> {REMOTE_MAX_MB} Mo) : gardée sur le serveur.")
    host, port, user, pwd = mailbox._imap()
    if not (host and user and pwd):
        raise BackupError("Boîte mail non connectée : sauvegarde gardée sur le serveur seulement.")
    msg = EmailMessage()
    msg["From"] = msg["To"] = user
    msg["Subject"] = f"Sauvegarde UniC AI — {name[len(PREFIX):-4]}"
    msg.set_content("Sauvegarde automatique d'UniC AI (devis, factures, clients, mémoire).\n"
                    "Pour restaurer : Paramètres › Moteur & santé › Sauvegardes › Restaurer, et choisis ce fichier .zip.\n"
                    "Ne supprime pas ce dossier.")
    msg.add_attachment(p.read_bytes(), maintype="application", subtype="zip", filename=name)
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=60) as box:
            box.login(user, pwd)
            box.create(REMOTE_FOLDER)   # déjà présent : réponse « NO », sans effet
            typ, _ = box.append(REMOTE_FOLDER, "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if typ != "OK":
                raise BackupError("La boîte mail a refusé la sauvegarde.")
            _prune_remote(box)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise BackupError(f"Boîte mail injoignable : {type(exc).__name__}. Sauvegarde gardée sur le serveur.") from exc
    when = datetime.now(timezone.utc).isoformat()
    _save_status(last_remote=when, last_remote_name=name, last_remote_error="")
    return {"ok": True, "folder": REMOTE_FOLDER, "at": when}


def _prune_remote(box: imaplib.IMAP4_SSL) -> None:
    """Supprime seulement NOS anciennes sauvegardes, seulement dans NOTRE dossier."""
    typ, _ = box.select(REMOTE_FOLDER)
    if typ != "OK":
        return
    typ, data = box.search(None, 'SUBJECT "Sauvegarde UniC AI"')
    ids = (data[0] or b"").split() if typ == "OK" else []
    old = ids[:-KEEP_REMOTE]
    for i in old:
        box.store(i, "+FLAGS", "\\Deleted")
    if old:
        box.expunge()
    box.close()


# ---------- restauration ----------

def restore(data: bytes) -> dict:
    """Remplace la base par celle d'une sauvegarde (après une sauvegarde de sécurité de l'état actuel)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
    except (zipfile.BadZipFile, ValueError) as exc:
        raise BackupError("Fichier illisible : choisis un fichier UniC_Sauvegarde_….zip.") from exc
    if "unic.db" not in names or manifest.get("app") != "UniC AI":
        raise BackupError("Ce fichier n'est pas une sauvegarde UniC AI.")
    safety = create("avant restauration")
    with _lock:
        tmp = settings.backups_path / ".restore.db"
        tmp.write_bytes(z.read("unic.db"))
        try:
            src = sqlite3.connect(str(tmp))
            try:
                if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("La base de cette sauvegarde est endommagée : rien n'a été changé.")
                live = sqlite3.connect(str(_db_file()))
                try:
                    src.backup(live)   # remplacement à chaud, cohérent
                finally:
                    live.close()
            finally:
                src.close()
        finally:
            tmp.unlink(missing_ok=True)
        for name in ("signature.png", "stamp.png"):
            if f"brand/{name}" in names:
                _signature().parent.mkdir(parents=True, exist_ok=True)
                _signature().with_name(name).write_bytes(z.read(f"brand/{name}"))
    _save_status(last_restore=datetime.now(timezone.utc).isoformat(), last_restore_from=manifest.get("created_at"))
    return {"ok": True, "restored_from": manifest.get("created_at"), "counts": manifest.get("counts"),
            "safety_backup": safety["name"]}


# ---------- tous les jours, tout seul ----------

def _due() -> bool:
    last = status().get("last_local")
    if not last:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    except ValueError:
        return True
    return age.total_seconds() >= EVERY_HOURS * 3600


def run_daily() -> dict | None:
    """Sauvegarde du jour (si due) puis dépôt hors serveur. Jamais d'exception : le serveur continue quoi qu'il arrive."""
    if not _due():
        return None
    try:
        made = create("automatique")
    except Exception as exc:
        logger.exception("Sauvegarde automatique impossible")
        _save_status(last_error=f"{type(exc).__name__}: {exc}"[:200])
        return None
    if offsite_available():
        try:
            push_offsite(made["name"])
        except BackupError as exc:
            _save_status(last_remote_error=str(exc))
    return made


def start_scheduler() -> None:
    """Fil discret : vérifie toutes les heures si la sauvegarde du jour est faite."""
    def loop():
        time.sleep(90)   # laisse le serveur démarrer
        while True:
            run_daily()
            time.sleep(3600)

    threading.Thread(target=loop, name="unic-backup", daemon=True).start()
