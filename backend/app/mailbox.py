"""Boîte mail : lecture IMAP (lecture seule) et envoi SMTP. Rien n'est envoyé sans appel explicite."""
from __future__ import annotations

import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings


def imap_configured() -> bool:
    return bool(settings.imap_host and (settings.imap_user or settings.smtp_user))


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


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


def fetch_recent(limit: int = 20) -> list[dict]:
    """Derniers e-mails de la boîte de réception, sans les marquer lus (BODY.PEEK)."""
    user = settings.imap_user or settings.smtp_user
    pwd = settings.imap_password or settings.smtp_password
    out: list[dict] = []
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as box:
        box.login(user, pwd)
        box.select("INBOX", readonly=True)
        _, data = box.search(None, "ALL")
        ids = (data[0] or b"").split()[-limit:]
        for num in reversed(ids):
            _, parts = box.fetch(num, "(BODY.PEEK[])")
            raw = parts[0][1] if parts and isinstance(parts[0], tuple) else None
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            out.append({
                "uid": (msg.get("Message-ID") or f"imap-{num.decode()}").strip(),
                "from_addr": parseaddr(_dec(msg.get("From")))[1] or _dec(msg.get("From")),
                "subject": _dec(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "body": _text_of(msg).strip()[:20000],
            })
    return out


def send(to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
