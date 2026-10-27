"""Sauvegardes : base complète (devis, factures, clients, mémoire…) + signature, chaque jour, gardées ici ET hors du serveur.

- Copie cohérente de la base SQLite (API de sauvegarde SQLite, même pendant l'utilisation), compressée en .zip.
- Hors serveur : déposée dans ta boîte Gmail, dossier « UniC-Sauvegardes » (IMAP APPEND, rien n'est envoyé à un tiers).
- Fichiers (plans, photos, documents reçus, fichiers créés) : déposés à part, dossier « UniC-Sauvegardes-Fichiers »,
  seulement les nouveaux ou modifiés (paquets de 18 Mo au plus, jamais effacés là-bas). Les PDF de devis, factures,
  bons et relevés n'y sont pas : ils se refont depuis la base. Restaurer un paquet : même bouton que la base.
- Jamais dans l'archive : la clé de chiffrement des secrets (.secret_key). Après une perte du disque, les connecteurs
  (Gmail, LinkedIn, site, voix) se reconnectent ; tout le reste revient.
- Restauration : une sauvegarde de sécurité de l'état actuel est faite juste avant.
- Copies hors serveur CHIFFRÉES si le patron choisit un mot de passe des sauvegardes (AES-256-GCM, clé tirée du mot de passe
  par scrypt). Le mot de passe n'est jamais gardé : seule la clé, chiffrée par le coffre (`secrets_box`), hors des archives.
  Gmail piraté = archives illisibles. Restaurer sur un nouveau serveur demande le mot de passe.
"""
from __future__ import annotations

import hashlib
import imaplib
import io
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import mailbox, secrets_box
from app.config import settings

logger = logging.getLogger("unic.backup")

PREFIX = "UniC_Sauvegarde_"
KEEP_LOCAL = 14
KEEP_REMOTE = 30
REMOTE_FOLDER = "UniC-Sauvegardes"
REMOTE_MAX_MB = 20
FILES_FOLDER = "UniC-Sauvegardes-Fichiers"
FILES_PART_MB = 18          # un paquet de fichiers par message (limite Gmail : 25 Mo pièces jointes comprises)
# ce qui ne se refait pas depuis la base ; les PDF de devis, factures, bons, relevés se régénèrent
FILE_DIRS = ("uploads", "signatures", "brand", "artifacts/generated", "artifacts/made", "artifacts/edited",
             "artifacts/diagrams", "artifacts/pdftools")
MAX_FILES_RESTORE_MB = 200
EVERY_HOURS = 24
MAX_RESTORE_MB = 300        # fichier .zip envoyé pour une restauration
MAX_DB_MB = 1024            # base décompressée (protège d'une « bombe » zip)
MAX_BRAND_MB = 15
ENC_MAGIC = b"UNICENC1"     # en-tête d'une copie chiffrée : MAGIC + sel (16) + nonce (12) + données chiffrées
ENC_SUFFIX = ".enc"
MIN_PASSWORD = 8
NEED_PASSWORD = "Sauvegarde chiffrée : entre le mot de passe des sauvegardes."
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
                counts[table] = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608 - liste fixe
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
        check = verify(name)   # relecture à blanc : la sauvegarde est PROUVÉE restaurable (ou le problème est signalé)
        if check["ok"]:
            _save_status(last_verified=manifest["created_at"], verify_error="")
        else:
            logger.error("Sauvegarde %s non restaurable : %s", name, check["problems"])
            _save_status(verify_error=("; ".join(check["problems"]))[:300])
        return {"name": name, "size": size, "counts": counts, "verified": check["ok"], "problems": check["problems"]}


def verify(name: str) -> dict:
    """TEST DE RESTAURATION à blanc : ouvre la sauvegarde dans un fichier temporaire (la vraie base n'est jamais touchée),
    vérifie l'intégrité de la base, la cohérence des clés étrangères et que les chiffres correspondent au manifeste.
    Une sauvegarde qu'on n'a jamais essayé de relire ne prouve rien : chaque sauvegarde est vérifiée à sa création."""
    import tempfile
    problems: list[str] = []
    counts: dict = {}
    try:
        path = path_of(name)
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
            if "unic.db" not in z.namelist():
                return {"ok": False, "problems": ["unic.db absent de l'archive."], "counts": {}}
            if z.getinfo("unic.db").file_size > MAX_DB_MB * 1024 * 1024:
                return {"ok": False, "problems": ["Base trop volumineuse."], "counts": {}}
            with tempfile.TemporaryDirectory(dir=settings.backups_path) as tmp:
                db_copy = Path(tmp) / "check.db"
                with z.open("unic.db") as src_file, db_copy.open("wb") as dst:
                    shutil.copyfileobj(src_file, dst, 1024 * 1024)
                con = sqlite3.connect(str(db_copy))
                try:
                    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        problems.append("Base endommagée (integrity_check).")
                    broken = con.execute("PRAGMA foreign_key_check").fetchall()
                    if broken:
                        problems.append(f"{len(broken)} lien(s) cassé(s) entre tables (clés étrangères).")
                    for table in (manifest.get("counts") or {}):
                        try:
                            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608 - noms issus de la liste fixe de _snapshot
                        except sqlite3.Error:
                            problems.append(f"Table {table} illisible.")
                        else:
                            if counts[table] != manifest["counts"][table]:
                                problems.append(f"{table} : {counts[table]} lus, {manifest['counts'][table]} attendus.")
                finally:
                    con.close()
    except BackupError as exc:
        problems.append(str(exc))
    except (zipfile.BadZipFile, OSError, ValueError, sqlite3.Error) as exc:
        problems.append(f"Archive illisible ({type(exc).__name__}).")
    return {"ok": not problems, "problems": problems, "counts": counts}


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


# ---------- chiffrement des copies hors serveur ----------

def _key_file() -> Path:
    return settings.backups_path / ".backup_key.json"   # jamais dans une archive (seuls la base et les fichiers y vont)


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def _stored() -> tuple[bytes, bytes] | None:
    """(sel, clé) du mot de passe en cours ; None si le chiffrement est coupé ou la clé illisible."""
    try:
        data = json.loads(_key_file().read_text(encoding="utf-8"))
        key = secrets_box.decrypt(data["key"])
        return (bytes.fromhex(data["salt"]), bytes.fromhex(key)) if key else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def encryption_on() -> bool:
    return _stored() is not None


def set_password(password: str) -> None:
    """Choisit (ou change) le mot de passe des sauvegardes. Les copies suivantes seront chiffrées avec ; les anciennes gardent
    le leur. Le mot de passe lui-même n'est écrit nulle part."""
    if len(password or "") < MIN_PASSWORD:
        raise BackupError(f"Mot de passe trop court : {MIN_PASSWORD} caractères minimum.")
    salt = os.urandom(16)
    key = _derive(password, salt)
    if _open(_seal_with(salt, key, b"essai"), password) != b"essai":   # contrôle avant de l'adopter
        raise BackupError("Chiffrement impossible sur ce serveur : rien n'a été changé.")
    path = _key_file()
    path.write_text(json.dumps({"salt": salt.hex(), "key": secrets_box.encrypt(key.hex()),
                                "at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_password() -> None:
    _key_file().unlink(missing_ok=True)


def _seal_with(salt: bytes, key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return ENC_MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, data, ENC_MAGIC)


def seal(data: bytes) -> bytes:
    """Chiffre une copie qui part hors du serveur (inchangée si aucun mot de passe n'est choisi)."""
    st = _stored()
    return _seal_with(*st, data) if st else data


def _open(data: bytes, password: str = "") -> bytes:
    """Déchiffre une copie (clé du serveur si c'est le même mot de passe, sinon le mot de passe donné). Non chiffrée : telle quelle."""
    if not data.startswith(ENC_MAGIC):
        return data
    salt, nonce, body = data[8:24], data[24:36], data[36:]
    keys = []
    st = _stored()
    if st and st[0] == salt:
        keys.append(st[1])
    if password:
        keys.append(_derive(password, salt))
    if not keys:
        raise BackupError(NEED_PASSWORD)
    for key in keys:
        try:
            return AESGCM(key).decrypt(nonce, body, ENC_MAGIC)
        except InvalidTag:
            continue
    raise BackupError("Mot de passe des sauvegardes incorrect (ou fichier abîmé) : rien n'a été changé.")


# ---------- hors serveur : boîte Gmail ----------

def offsite_available() -> bool:
    return mailbox.imap_configured()


def push_offsite(name: str) -> dict:
    """Dépose l'archive dans la boîte mail (dossier UniC-Sauvegardes) et ne garde que les 30 dernières là-bas."""
    p = path_of(name)
    if p.stat().st_size > REMOTE_MAX_MB * 1024 * 1024:
        raise BackupError(f"Sauvegarde trop lourde pour la boîte mail (> {REMOTE_MAX_MB} Mo) : gardée sur le serveur.")
    data = seal(p.read_bytes())
    locked = data.startswith(ENC_MAGIC)
    _append(REMOTE_FOLDER, f"Sauvegarde UniC AI — {name[len(PREFIX):-4]}",
            "Sauvegarde automatique d'UniC AI (devis, factures, clients, mémoire).\n"
            "Pour restaurer : Paramètres › Moteur & santé › Sauvegardes › Restaurer, et choisis ce fichier.\n"
            + ("Copie CHIFFRÉE : le mot de passe des sauvegardes sera demandé sur un nouveau serveur.\n" if locked else "")
            + "Ne supprime pas ce dossier.", name + (ENC_SUFFIX if locked else ""), data, prune=True)
    when = datetime.now(timezone.utc).isoformat()
    _save_status(last_remote=when, last_remote_name=name, last_remote_error="")
    return {"ok": True, "folder": REMOTE_FOLDER, "at": when}


def _append(folder: str, subject: str, body: str, filename: str, data: bytes, prune: bool = False) -> None:
    """Dépose un message (une archive jointe) dans un dossier de la boîte du patron. Rien n'est envoyé à personne."""
    host, port, user, pwd = mailbox._imap()
    if not (host and user and pwd):
        raise BackupError("Boîte mail non connectée : sauvegarde gardée sur le serveur seulement.")
    msg = EmailMessage()
    msg["From"] = msg["To"] = user
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(data, maintype="application", subtype="octet-stream" if filename.endswith(ENC_SUFFIX) else "zip", filename=filename)
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=60) as box:
            box.login(user, pwd)
            box.create(folder)   # déjà présent : réponse « NO », sans effet
            typ, _ = box.append(folder, "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if typ != "OK":
                raise BackupError("La boîte mail a refusé la sauvegarde.")
            if prune:
                _prune_remote(box)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise BackupError(f"Boîte mail injoignable : {type(exc).__name__}. Sauvegarde gardée sur le serveur.") from exc


# ---------- fichiers hors serveur (incrémental) ----------

def _index_file() -> Path:
    return settings.backups_path / "files_index.json"


def _index() -> dict:
    try:
        return json.loads(_index_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _changed_files() -> tuple[list[tuple[str, Path, str]], list[str]]:
    """(chemin relatif, fichier, empreinte taille:date) des fichiers nouveaux ou modifiés ; et ceux trop lourds pour un message."""
    root = settings.storage_path
    known = _index()
    todo, heavy = [], []
    for d in FILE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.is_symlink() or f.name.startswith("."):
                continue
            st = f.stat()
            rel, mark = f.relative_to(root).as_posix(), f"{st.st_size}:{int(st.st_mtime)}"
            if known.get(rel) == mark:
                continue
            if st.st_size > FILES_PART_MB * 1024 * 1024:
                heavy.append(rel)
                continue
            todo.append((rel, f, mark))
    return todo, heavy


def push_files_offsite() -> dict:
    """Dépose les fichiers nouveaux ou modifiés, par paquets, dans la boîte du patron. L'index n'avance qu'après un dépôt réussi."""
    with _lock:
        todo, heavy = _changed_files()
        parts, sent, limit = 0, 0, FILES_PART_MB * 1024 * 1024
        known = _index()
        while todo:
            batch, size = [], 0
            while todo and (not batch or size + todo[0][1].stat().st_size <= limit):
                item = todo.pop(0)
                batch.append(item)
                size += item[1].stat().st_size
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
            name = f"{PREFIX}Fichiers_{stamp}_{parts + 1}.zip"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for rel, f, _mark in batch:
                    z.write(f, f"files/{rel}")
                z.writestr("manifest.json", json.dumps({"app": "UniC AI", "kind": "files", "format": 1,
                                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                                        "files": [rel for rel, _f, _m in batch]}, ensure_ascii=False))
            data = seal(buf.getvalue())
            locked = data.startswith(ENC_MAGIC)
            _append(FILES_FOLDER, f"Fichiers UniC AI — {stamp} ({len(batch)})",
                    "Fichiers d'UniC AI (plans, photos, documents reçus, fichiers créés) : nouveaux ou modifiés depuis le dépôt précédent.\n"
                    "Pour les remettre : Paramètres › Moteur & santé › Sauvegardes › Restaurer, et choisis ce fichier.\n"
                    + ("Copie CHIFFRÉE : le mot de passe des sauvegardes sera demandé sur un nouveau serveur.\n" if locked else "")
                    + "Ne supprime pas ce dossier : chaque message ne contient que ce qui a changé.", name + (ENC_SUFFIX if locked else ""), data)
            for rel, _f, mark in batch:
                known[rel] = mark
            _index_file().write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
            parts += 1
            sent += len(batch)
    when = datetime.now(timezone.utc).isoformat()
    _save_status(last_files=when, files_heavy=heavy[:20], last_files_error="")
    return {"ok": True, "files": sent, "parts": parts, "too_heavy": heavy, "folder": FILES_FOLDER, "at": when}


def restore_files(z: zipfile.ZipFile) -> dict:
    """Remet les fichiers d'un paquet à leur place (jamais hors des dossiers sauvegardés, jamais de chemin piégé)."""
    root = settings.storage_path.resolve()
    if sum(i.file_size for i in z.infolist()) > MAX_FILES_RESTORE_MB * 1024 * 1024:
        raise BackupError("Paquet trop volumineux : rien n'a été changé.")
    plan = []
    for info in z.infolist():
        if info.is_dir() or not info.filename.startswith("files/"):
            continue
        rel = info.filename[len("files/"):]
        dest = (root / rel).resolve()
        if ".." in Path(rel).parts or not any(dest.is_relative_to((root / d).resolve()) for d in FILE_DIRS):
            raise BackupError(f"Chemin refusé dans le paquet : {rel[:80]}. Rien n'a été changé.")
        plan.append((info, dest))
    for info, dest in plan:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src_file, dest.open("wb") as dst:
            shutil.copyfileobj(src_file, dst, 1024 * 1024)
    return {"ok": True, "kind": "files", "restored_files": len(plan)}


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

def restore(data: bytes, password: str = "") -> dict:
    """Remplace la base par celle d'une sauvegarde (après une sauvegarde de sécurité de l'état actuel).
    Copie chiffrée : déchiffrée d'abord (clé du serveur, ou mot de passe des sauvegardes sur un nouveau serveur)."""
    data = _open(data, password)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
    except (zipfile.BadZipFile, ValueError) as exc:
        raise BackupError("Fichier illisible : choisis un fichier UniC_Sauvegarde_….zip.") from exc
    if manifest.get("app") == "UniC AI" and manifest.get("kind") == "files":   # paquet de fichiers : la base n'est pas touchée
        with _lock:
            return restore_files(z)
    if "unic.db" not in names or manifest.get("app") != "UniC AI":
        raise BackupError("Ce fichier n'est pas une sauvegarde UniC AI.")
    if z.getinfo("unic.db").file_size > MAX_DB_MB * 1024 * 1024:
        raise BackupError("Base trop volumineuse dans cette sauvegarde : rien n'a été changé.")
    safety = create("avant restauration")
    with _lock:
        tmp = settings.backups_path / ".restore.db"
        with z.open("unic.db") as src_file, tmp.open("wb") as dst_file:
            shutil.copyfileobj(src_file, dst_file, 1024 * 1024)   # par morceaux : la base ne passe jamais entière en mémoire
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
            if f"brand/{name}" in names and z.getinfo(f"brand/{name}").file_size <= MAX_BRAND_MB * 1024 * 1024:
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
        try:
            push_files_offsite()
        except (BackupError, OSError) as exc:
            _save_status(last_files_error=str(exc)[:300])
    return made


def start_scheduler() -> None:
    """Fil discret : vérifie toutes les heures si la sauvegarde du jour est faite."""
    if os.environ.get("UNIC_NO_BACKGROUND"):   # tests : pas de fil de fond (comme la surveillance et les alertes) ; run_daily() s'appelle à la main
        return

    def loop():
        from app import selfcare
        selfcare.beat("sauvegarde", 3600, restart=start_scheduler)
        time.sleep(90)   # laisse le serveur démarrer
        while True:
            selfcare.beat("sauvegarde", 3600, restart=start_scheduler)   # pouls : la surveillance voit s'il s'endort
            run_daily()
            time.sleep(3600)

    threading.Thread(target=loop, name="unic-backup", daemon=True).start()
