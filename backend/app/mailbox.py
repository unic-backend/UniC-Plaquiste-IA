"""Boîte mail : lecture IMAP (lecture seule), mise à la corbeille sur clic du patron, et envoi SMTP. Rien n'est envoyé sans appel explicite."""
from __future__ import annotations

import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings


#: compte Gmail connecté depuis l'appli (mémoire du serveur, rechargé au démarrage) ; les variables d'environnement gagnent
_RT = {"user": "", "password": ""}


def set_runtime(user: str, password: str) -> None:
    _RT["user"], _RT["password"] = user, password


def _imap() -> tuple[str, int, str, str]:
    if settings.imap_host:
        return (settings.imap_host, settings.imap_port, settings.imap_user or settings.smtp_user,
                settings.imap_password or settings.smtp_password)
    return "imap.gmail.com", 993, _RT["user"], _RT["password"]


def _smtp() -> tuple[str, int, str, str, str]:
    if settings.smtp_host:
        return (settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_password,
                settings.smtp_from or settings.smtp_user)
    return "smtp.gmail.com", 587, _RT["user"], _RT["password"], _RT["user"]


def imap_configured() -> bool:
    host, _port, user, pwd = _imap()
    return bool(host and user and (pwd or settings.imap_host))


def smtp_configured() -> bool:
    host, _port, user, pwd, _from = _smtp()
    return bool(host and user and pwd)


def _dec(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _text_of(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _row(num: bytes, raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    return {
        "uid": (msg.get("Message-ID") or f"imap-{num.decode()}").strip(),
        "from_addr": parseaddr(_dec(msg.get("From")))[1] or _dec(msg.get("From")),
        "subject": _dec(msg.get("Subject")),
        "date": msg.get("Date", ""),
        "body": _text_of(msg).strip()[:20000],
    }


def _load(box: imaplib.IMAP4_SSL, ids: list[bytes]) -> list[dict]:
    """Charge les mails (du plus récent au plus ancien) sans les marquer lus (BODY.PEEK)."""
    out: list[dict] = []
    for num in reversed(ids):
        _, parts = box.fetch(num, "(BODY.PEEK[])")
        raw = parts[0][1] if parts and isinstance(parts[0], tuple) else None
        if raw:
            out.append(_row(num, raw))
    return out


def fetch_recent(limit: int = 20) -> list[dict]:
    """Derniers e-mails de la boîte de réception, sans les marquer lus (BODY.PEEK)."""
    host, port, user, pwd = _imap()
    with imaplib.IMAP4_SSL(host, port) as box:
        box.login(user, pwd)
        box.select("INBOX", readonly=True)
        _, data = box.search(None, "ALL")
        return _load(box, (data[0] or b"").split()[-limit:])


def _quoted(text: str) -> str:
    """Texte de recherche rendu inoffensif pour IMAP : une seule ligne, guillemets et barres échappés, longueur bornée."""
    flat = " ".join("".join(ch for ch in str(text) if ch.isprintable() or ch.isspace()).split())[:200]   # sans NUL ni caractères de contrôle
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _all_mail_folder(box: imaplib.IMAP4_SSL) -> str | None:
    """Dossier « Tous les messages » de Gmail (reçus ET envoyés, archivés compris), repéré par son attribut \\All."""
    try:
        _, rows = box.list()
        for row in rows or []:
            line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
            if "\\All" in line and ' "/" ' in line:
                return line.rsplit(' "/" ', 1)[-1].strip().strip('"')
    except imaplib.IMAP4.error:
        pass
    return None


def search(query: str, limit: int = 10) -> list[dict]:
    """Recherche dans TOUTE la boîte (lecture seule). Gmail : syntaxe Gmail (from:, to:, subject:, after:2026/01/01, has:attachment…)
    sur « Tous les messages », donc les envoyés et les conversations entières. Autre fournisseur : objet, expéditeur ou texte dans la réception."""
    host, port, user, pwd = _imap()
    limit = max(1, min(int(limit), 25))
    with imaplib.IMAP4_SSL(host, port) as box:
        box.login(user, pwd)
        if host == "imap.gmail.com":
            folder = _all_mail_folder(box) or "INBOX"
            box.select(f'"{folder}"', readonly=True)
            _, data = box.search("UTF-8", "X-GM-RAW", _quoted(query))
        else:
            box.select("INBOX", readonly=True)
            q = _quoted(query)
            _, data = box.search("UTF-8", "OR", "OR", "SUBJECT", q, "FROM", q, "BODY", q)
        return _load(box, (data[0] or b"").split()[-limit:])


_TRASH_FALLBACKS = ("[Gmail]/Trash", "[Gmail]/Corbeille", "[Google Mail]/Trash", "Trash")


def _trash_folder(box: imaplib.IMAP4_SSL) -> str | None:
    """Dossier corbeille du compte : repéré par son attribut \\Trash (quelle que soit la langue), sinon noms usuels."""
    try:
        _, rows = box.list()
        for row in rows or []:
            line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
            if "\\Trash" in line:
                name = line.rsplit(' "/" ', 1)[-1].strip() if ' "/" ' in line else line.rsplit(" ", 1)[-1]
                return name.strip().strip('"')
    except imaplib.IMAP4.error:
        pass
    for name in _TRASH_FALLBACKS:
        try:
            if box.select(f'"{name}"', readonly=True)[0] == "OK":
                return name
        except imaplib.IMAP4.error:
            continue
    return None


def trash(message_ids: list[str]) -> dict:
    """Met à la CORBEILLE de Gmail (récupérable ~30 jours) les mails identifiés par leur Message-ID. Jamais de suppression définitive.
    Appelé seulement après le clic du patron."""
    host, port, user, pwd = _imap()
    moved, missing = [], []
    with imaplib.IMAP4_SSL(host, port) as box:
        box.login(user, pwd)
        folder = _trash_folder(box)
        if not folder:
            raise RuntimeError("Dossier Corbeille introuvable sur ce compte : rien n'a été touché.")
        box.select("INBOX")
        for mid in message_ids:
            safe = mid.replace('"', "").strip()
            typ, data = box.uid("SEARCH", None, "HEADER", "Message-ID", f'"{safe}"')
            uids = (data[0] or b"").split() if typ == "OK" else []
            if not uids:
                missing.append(mid)
                continue
            uid = uids[-1].decode()
            if box.uid("COPY", uid, f'"{folder}"')[0] != "OK":   # copie réussie d'abord : sinon le mail reste où il est
                missing.append(mid)
                continue
            box.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            moved.append(mid)
        if moved:
            box.expunge()
    return {"moved": moved, "missing": missing}


def send(to_addr: str, subject: str, body: str, attachments: list[tuple[str, str, bytes]] | None = None) -> None:
    """attachments : [(nom du fichier, type MIME, contenu)] — PDF, Excel… joints tels quels."""
    host, port, user, pwd, sender = _smtp()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    for filename, mime, data in attachments or []:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=filename)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, pwd)
        smtp.send_message(msg)
