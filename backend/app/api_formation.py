"""Formation UniC : cours écrit, exercices corrigés par le moteur, suivi par élève. Aucun appel à l'IA."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import formation
from app.database import get_db
from app.models import User
from app.security import get_current_user

router = APIRouter(prefix="/formation", tags=["formation"])


def _wrap(fn, *a):
    try:
        return fn(*a)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class Eleve(BaseModel):
    eleve: str = Field(min_length=1, max_length=40)


class LeconIn(Eleve):
    lecon: str = Field(max_length=20)


class QuizIn(Eleve):
    question: str = Field(max_length=10)
    choix: int = Field(ge=0, le=9)
    certitude: str = Field(max_length=10)


class CorrigerIn(Eleve):
    type: str = Field(max_length=10)
    seed: int = Field(ge=0, le=10**9)
    reponses: dict[str, float | None] = Field(default_factory=dict, max_length=10)
    examen: bool = False


@router.get("")
def cours(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {**formation.course(db), "eleves": formation.learners(db)}


@router.get("/exercice")
def exercice(type: str, seed: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(formation.exercise, db, type, max(0, min(seed, 10**9)))


@router.post("/exercice/corriger")
def corriger(body: CorrigerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(formation.grade, db, body.type, body.seed, body.reponses, body.eleve, body.examen)


@router.post("/quiz")
def quiz(body: QuizIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(formation.answer_quiz, db, body.eleve, body.question, body.choix, body.certitude)


@router.post("/lecon")
def lecon(body: LeconIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(formation.mark_lesson, db, body.eleve, body.lecon)


@router.post("/suivi")
def suivi(body: Eleve, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _wrap(formation.progress, db, body.eleve)
