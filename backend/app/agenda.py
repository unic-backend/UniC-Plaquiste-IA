"""Agenda des chantiers : visites, métrés, poses, livraisons, rendez-vous. Conflits d'horaires signalés, jamais cachés."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AppSetting, Appointment, Customer

KINDS = {"visite": "Visite", "metre": "Métré", "pose": "Pose", "livraison": "Livraison", "rdv": "Rendez-vous", "tache": "À faire", "autre": "Autre"}
DEFAULT_MIN = {"visite": 60, "metre": 90, "pose": 480, "livraison": 60, "rdv": 60, "tache": 30, "autre": 60}
FEED_KEY = "agenda_feed_token"   # lien secret du calendrier du téléphone (abonnement .ics), coupé tant que le patron ne l'active pas
FEED_PAST_DAYS, FEED_NEXT_DAYS = 30, 365
# Dakar : UTC+0 toute l'année. Les heures saisies sont donc directement des heures UTC.


class AgendaError(Exception):
    pass


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_dt(value: str) -> datetime:
    """« 2026-10-06 09:30 », « 2026-10-06T09:30 » ou ISO complet."""
    v = (value or "").strip().replace(" ", "T", 1)
    try:
        d = datetime.fromisoformat(v)
    except ValueError as exc:
        raise AgendaError("Date/heure illisible : utilise AAAA-MM-JJ HH:MM.") from exc
    return _aware(d)


JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")


def fr_when(d: datetime) -> str:
    """« jeudi 30 octobre 2026 à 10 h 00 » (heure de Dakar = UTC) : calculé ici, l'IA n'a qu'à le répéter, jamais à le deviner."""
    d = _aware(d)
    day = "1er" if d.day == 1 else str(d.day)
    return f"{JOURS[d.weekday()]} {day} {MOIS[d.month - 1]} {d.year} à {d.hour} h {d.minute:02d}"


def to_dict(a: Appointment) -> dict:
    s, e = _aware(a.start_at), _aware(a.end_at)
    return {"id": a.id, "title": a.title, "kind": a.kind, "kind_label": KINDS.get(a.kind, a.kind),
            "quand": fr_when(s), "start_at": s.isoformat(), "end_at": e.isoformat() if e else None, "location": a.location,
            "client_name": a.client_name, "phone": a.phone, "notes": a.notes, "status": a.status,
            "remind_minutes": a.remind_minutes}


def conflicts(db: Session, start: datetime, end: datetime, exclude_id: str | None = None) -> list[Appointment]:
    rows = db.query(Appointment).filter(Appointment.status == "planned").all()
    out = []
    for r in rows:
        if r.id == exclude_id or r.kind == "tache":   # une tâche a une échéance, pas un créneau : jamais un conflit
            continue
        rs, re_ = _aware(r.start_at), _aware(r.end_at) or _aware(r.start_at) + timedelta(minutes=60)
        if rs < end and start < re_:
            out.append(r)
    return out


def create(db: Session, *, title: str, start: str, kind: str = "rdv", duration_min: int | None = None,
           location: str = "", client_name: str = "", phone: str = "", notes: str = "", remind_minutes: int = 60) -> tuple[Appointment, list]:
    title = (title or "").strip()
    if len(title) < 2:
        raise AgendaError("Titre manquant (ex. « Métré salon Pape Diop »).")
    kind = kind if kind in KINDS else "autre"
    s = parse_dt(start)
    dur = int(duration_min or DEFAULT_MIN[kind])
    if not 5 <= dur <= 60 * 24 * 7:
        raise AgendaError("Durée invalide.")
    e = s + timedelta(minutes=dur)
    cust = None
    if client_name.strip():
        cust = next((c for c in db.query(Customer).all() if (c.name or "").strip().lower() == client_name.strip().lower()), None)
    clash = [] if kind == "tache" else conflicts(db, s, e)
    a = Appointment(title=title[:255], kind=kind, start_at=s, end_at=e, location=location[:255], client_name=client_name[:255],
                    phone=(phone or (getattr(cust, "phone", "") or ""))[:64], customer_id=cust.id if cust else None,
                    notes=notes, remind_minutes=max(0, min(int(remind_minutes), 24 * 60)))
    db.add(a)
    db.flush()
    return a, clash


def upcoming(db: Session, days: int = 14, now: datetime | None = None, include_past_today: bool = True) -> list[Appointment]:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) if include_past_today else now
    rows = db.query(Appointment).filter(Appointment.status == "planned").all()
    rows = [r for r in rows if start <= _aware(r.start_at) <= now + timedelta(days=days)]
    return sorted(rows, key=lambda r: _aware(r.start_at))


def overdue_tasks(db: Session, now: datetime | None = None) -> list[Appointment]:
    """Tâches pas encore faites dont l'échéance est passée (avant aujourd'hui) : elles restent visibles jusqu'à « Fait »."""
    day0 = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.query(Appointment).filter(Appointment.status == "planned", Appointment.kind == "tache").all()
    return sorted((r for r in rows if _aware(r.start_at) < day0), key=lambda r: _aware(r.start_at))


# ---------- calendrier du téléphone (abonnement iCalendar, RFC 5545) ----------

def feed_token(db: Session) -> str:
    row = db.get(AppSetting, FEED_KEY)
    return (row.value or "") if row else ""


def set_feed(db: Session, on: bool) -> str:
    """Active (nouveau lien secret : l'ancien cesse de marcher) ou coupe le flux. Rend le jeton actif ('' si coupé)."""
    token = secrets.token_urlsafe(32) if on else ""
    row = db.get(AppSetting, FEED_KEY)
    if row is None:
        db.add(AppSetting(key=FEED_KEY, value=token))
    else:
        row.value = token
    db.commit()
    return token


def feed_matches(db: Session, token: str) -> bool:
    good = feed_token(db)
    return bool(good) and secrets.compare_digest(good.encode(), (token or "").encode())


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line_: str) -> str:
    """Lignes de 75 octets au plus, suite précédée d'un espace (sans couper un caractère accentué)."""
    out, cur = [], ""
    for ch in line_:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ""
        cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def ics(db: Session, now: datetime | None = None) -> str:
    """Rendez-vous et tâches (prévus ou faits, jamais annulés) du mois passé à l'an prochain. Ni téléphone ni notes :
    le lien peut circuler, il ne montre que l'essentiel (quoi, quand, où, qui)."""
    now = now or datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=FEED_PAST_DAYS), now + timedelta(days=FEED_NEXT_DAYS)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UniC Plaquiste//UniC AI//FR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:UniC — chantiers", "X-WR-TIMEZONE:Africa/Dakar", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    rows = db.query(Appointment).filter(Appointment.status != "cancelled").all()
    for a in sorted(rows, key=lambda r: _aware(r.start_at)):
        s = _aware(a.start_at)
        if not lo <= s <= hi:
            continue
        e = _aware(a.end_at) or s + timedelta(minutes=DEFAULT_MIN.get(a.kind, 60))
        label = KINDS.get(a.kind, a.kind)
        title = a.title if a.title.lower().startswith(label.lower()) else f"{label} · {a.title}"
        if a.status == "done":
            title = "✓ " + title
        desc = " · ".join(x for x in (a.client_name, a.location) if x)
        lines += ["BEGIN:VEVENT", f"UID:{a.id}@unic-ai", f"DTSTAMP:{stamp}", f"DTSTART:{s.strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTEND:{e.strftime('%Y%m%dT%H%M%SZ')}", f"SUMMARY:{_esc(title)}"]
        if a.location:
            lines.append(f"LOCATION:{_esc(a.location)}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc(desc)}")
        lines.append("STATUS:CONFIRMED")
        if a.status == "planned" and a.remind_minutes:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(title)}", f"TRIGGER:-PT{int(a.remind_minutes)}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def line(a: Appointment) -> str:
    s = _aware(a.start_at)
    who = f" — {a.client_name}" if a.client_name else ""
    where = f" — {a.location}" if a.location else ""
    return f"{s.strftime('%H:%M')} {KINDS.get(a.kind, a.kind)} : {a.title}{who}{where}"
