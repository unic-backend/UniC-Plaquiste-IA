"""Agenda des chantiers : visites, métrés, poses, livraisons, rendez-vous. Conflits d'horaires signalés, jamais cachés."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Appointment, Customer

KINDS = {"visite": "Visite", "metre": "Métré", "pose": "Pose", "livraison": "Livraison", "rdv": "Rendez-vous", "autre": "Autre"}
DEFAULT_MIN = {"visite": 60, "metre": 90, "pose": 480, "livraison": 60, "rdv": 60, "autre": 60}
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


def to_dict(a: Appointment) -> dict:
    s, e = _aware(a.start_at), _aware(a.end_at)
    return {"id": a.id, "title": a.title, "kind": a.kind, "kind_label": KINDS.get(a.kind, a.kind),
            "start_at": s.isoformat(), "end_at": e.isoformat() if e else None, "location": a.location,
            "client_name": a.client_name, "phone": a.phone, "notes": a.notes, "status": a.status,
            "remind_minutes": a.remind_minutes}


def conflicts(db: Session, start: datetime, end: datetime, exclude_id: str | None = None) -> list[Appointment]:
    rows = db.query(Appointment).filter(Appointment.status == "planned").all()
    out = []
    for r in rows:
        if r.id == exclude_id:
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
    clash = conflicts(db, s, e)
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


def line(a: Appointment) -> str:
    s = _aware(a.start_at)
    who = f" — {a.client_name}" if a.client_name else ""
    where = f" — {a.location}" if a.location else ""
    return f"{s.strftime('%H:%M')} {KINDS.get(a.kind, a.kind)} : {a.title}{who}{where}"
