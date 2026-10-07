"""Terrain : pointage chantier (arrivée/départ, GPS) et signature client sur un devis."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Project, QuoteAcceptance, Quotation, SiteCheckin, User
from app.security import get_current_user
from app.services import audit

router = APIRouter(tags=["terrain"])
MAX_SIGNATURE_BYTES = 300_000
MAX_CLOCK_SKEW_S = 60   # une heure d'appareil dans le futur au-delà de 1 min est refusée


class CheckinIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    kind: str = Field(pattern="^(in|out)$")
    project_id: str | None = None
    at: datetime | None = None            # heure de l'appareil (pointage fait hors réseau puis envoyé plus tard)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    note: str = Field(default="", max_length=500)


def _checkin_out(c: SiteCheckin, project_name: str | None = None) -> dict:
    return {"id": c.id, "kind": c.kind, "project_id": c.project_id, "project": project_name, "at": c.at.isoformat(),
            "lat": c.lat, "lon": c.lon, "accuracy_m": c.accuracy_m, "note": c.note}


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.post("/checkins")
def create_checkin(body: CheckinIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Enregistre un pointage. Rejouer le même client_id renvoie le pointage déjà enregistré (aucun doublon)."""
    existing = db.query(SiteCheckin).filter(SiteCheckin.client_id == body.client_id).first()
    if existing:
        return {**_checkin_out(existing), "duplicate": True}
    if body.project_id and db.get(Project, body.project_id) is None:
        raise HTTPException(404, "Chantier introuvable.")
    now = datetime.now(timezone.utc)
    at = _aware(body.at) if body.at else now
    if (at - now).total_seconds() > MAX_CLOCK_SKEW_S:
        raise HTTPException(400, "Heure de l'appareil dans le futur : vérifie la date du téléphone.")
    if (body.lat is None) != (body.lon is None):
        raise HTTPException(400, "Latitude et longitude vont ensemble.")
    c = SiteCheckin(client_id=body.client_id, project_id=body.project_id, kind=body.kind, at=at, lat=body.lat,
                    lon=body.lon, accuracy_m=body.accuracy_m, note=body.note.strip(), user_id=user.id)
    db.add(c)
    audit(db, user.id, "checkin_" + body.kind, "project", body.project_id or "", f"{at.isoformat()}")
    db.commit()
    return _checkin_out(c)


@router.get("/checkins")
def list_checkins(project_id: str = "", limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(SiteCheckin)
    if project_id:
        q = q.filter(SiteCheckin.project_id == project_id)
    names = {p.id: p.name for p in db.query(Project).all()}
    rows = q.order_by(SiteCheckin.at.desc()).limit(max(1, min(limit, 200))).all()
    return [_checkin_out(c, names.get(c.project_id or "")) for c in rows]


@router.get("/checkins/summary")
def checkin_summary(project_id: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Heures par chantier : chaque arrivée est appariée au départ suivant. Arrivée sans départ = « en cours », jamais comptée."""
    q = db.query(SiteCheckin)
    if project_id:
        q = q.filter(SiteCheckin.project_id == project_id)
    names = {p.id: p.name for p in db.query(Project).all()}
    totals: dict[str, float] = {}
    open_since: dict[str, datetime] = {}
    for c in q.order_by(SiteCheckin.at).all():
        key = c.project_id or ""
        if c.kind == "in":
            open_since[key] = _aware(c.at)
        elif key in open_since:
            totals[key] = totals.get(key, 0.0) + max((_aware(c.at) - open_since.pop(key)).total_seconds(), 0.0)
    return {"chantiers": [{"project_id": k or None, "project": names.get(k) if k else "Sans chantier", "heures": round(v / 3600, 2)}
                          for k, v in totals.items()],
            "en_cours": [{"project_id": k or None, "project": names.get(k) if k else "Sans chantier", "depuis": t.isoformat()}
                         for k, t in open_since.items()]}


# ---------- signature client sur un devis ----------

class SignatureIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    image: str = Field(min_length=20, max_length=600_000)   # data:image/png;base64,…
    consent: bool = False


def quote_hash(q: Quotation) -> str:
    """Empreinte du contenu engageant du devis (lignes, prix, totaux) : change si le devis est modifié après signature."""
    body = {"n": q.number, "v": q.version, "cur": q.currency, "sub": q.subtotal, "vat": q.vat_rate, "tot": q.total,
            "items": [[it.position, it.description, it.quantity, it.unit, it.unit_price, it.total]
                      for it in sorted(q.items, key=lambda x: x.position)]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _acceptance_out(a: QuoteAcceptance, q: Quotation) -> dict:
    return {"id": a.id, "signer_name": a.signer_name, "signed_at": a.signed_at.isoformat(), "quote_number": a.quote_number,
            "quote_total": a.quote_total, "unchanged_since_signature": a.content_hash == quote_hash(q)}


@router.post("/quotes/{qid}/signature")
def sign_quote(qid: str, body: SignatureIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Capture le « bon pour accord » du client (nom + signature dessinée). Ne change pas le statut du devis."""
    q = db.get(Quotation, qid)
    if q is None:
        raise HTTPException(404, "Devis introuvable.")
    if not body.consent:
        raise HTTPException(400, "Le client doit cocher « Bon pour accord » avant de signer.")
    m = re.fullmatch(r"data:image/png;base64,([A-Za-z0-9+/=]+)", body.image)
    if not m:
        raise HTTPException(400, "Signature invalide (image PNG attendue).")
    try:
        raw = base64.b64decode(m.group(1), validate=True)
    except ValueError:
        raise HTTPException(400, "Signature invalide.")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > MAX_SIGNATURE_BYTES:
        raise HTTPException(400, "Signature invalide ou trop lourde.")
    a = QuoteAcceptance(quotation_id=q.id, signer_name=body.name.strip(), image_path="", quote_number=q.number,
                        quote_version=q.version or 1, quote_total=q.total, content_hash=quote_hash(q),
                        ip=(request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else ""))[:64],
                        user_agent=request.headers.get("user-agent", "")[:255])
    db.add(a)
    db.flush()
    folder = settings.storage_path / "signatures"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{a.id}.png"
    dest.write_bytes(raw)
    a.image_path = str(dest)
    audit(db, user.id, "quote_signed", "quotation", q.id, f"{q.number} par {a.signer_name}")
    db.commit()
    return _acceptance_out(a, q)


@router.get("/quotes/{qid}/signature")
def quote_signatures(qid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.get(Quotation, qid)
    if q is None:
        raise HTTPException(404, "Devis introuvable.")
    rows = db.query(QuoteAcceptance).filter(QuoteAcceptance.quotation_id == qid).order_by(QuoteAcceptance.signed_at.desc()).all()
    return [_acceptance_out(a, q) for a in rows]


@router.get("/signatures/{sid}.png")
def signature_image(sid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(QuoteAcceptance, sid)
    if a is None:
        raise HTTPException(404, "Signature introuvable.")
    return FileResponse(a.image_path, media_type="image/png")
