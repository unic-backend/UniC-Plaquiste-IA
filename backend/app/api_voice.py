"""Voix : état, connexion ElevenLabs, voix disponibles, clonage de la voix du patron, lecture."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import voice
from app.services import audit, read_upload
from app.database import get_db
from app.models import User
from app.security import get_current_user

router = APIRouter(prefix="/voice", tags=["voice"])


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, str(exc))


class KeyIn(BaseModel):
    key: str


class SelectIn(BaseModel):
    voice_id: str


class SpeakIn(BaseModel):
    text: str
    voice_id: str = ""


@router.get("")
def voice_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return voice.status(db)


@router.post("/connect")
def voice_connect(body: KeyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = _wrap(voice.connect, db, body.key)
    audit(db, user.id, "voice_connect", "voice", "")
    db.commit()
    return out


@router.delete("/connect")
def voice_disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = voice.disconnect(db)
    audit(db, user.id, "voice_disconnect", "voice", "")
    db.commit()
    return out


@router.get("/voices")
def voice_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(voice.list_voices, db)


@router.post("/select")
def voice_select(body: SelectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = voice.select(db, body.voice_id)
    db.commit()
    return out


@router.post("/clone")
async def voice_clone(name: str = Form("Ma voix"), own_voice: bool = Form(False), file: UploadFile = File(...),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    audio = await read_upload(file, 10, "Échantillon")
    out = _wrap(voice.clone, db, name, audio, file.filename or "", file.content_type or "", own_voice)
    audit(db, user.id, "voice_clone", "voice", out["id"])
    db.commit()
    return out


@router.delete("/voices/{voice_id}")
def voice_delete(voice_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = _wrap(voice.delete_voice, db, voice_id)
    audit(db, user.id, "voice_delete", "voice", voice_id)
    db.commit()
    return out


@router.post("/speak")
def voice_speak(body: SpeakIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    audio = _wrap(voice.speak, db, body.text, body.voice_id)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
