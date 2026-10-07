"""Savoir validé : ce que Claude a bien répondu et que le patron a approuvé (👍).

Claude indisponible → le moteur local cherche ici. Une réponse n'est rendue que si la question est quasi la même
(la plupart des mots utiles retrouvés) ; sinon « je ne sais pas » : jamais de réponse inventée à la place.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app import retrieval
from app.models import LearnedAnswer, Message

MIN_COVERAGE = 0.7   # part des mots utiles de la question retrouvés dans une question validée
MIN_WORDS = 2
REFUSED_PREFIXES = ("Claude n'a pas pu répondre", "Je n'ai pas cette information", "Je ne peux pas aider")


# Une demande d'action (créer, envoyer, corriger…) ne se rejoue jamais depuis un ancien savoir : elle change des documents.
ACTION = re.compile(r"\b(cr[eé]e|cr[eé]er|pr[eé]pare|fais|fait-moi|g[eé]n[eè]re|[eé]tabli|[eé]mets|r[eé]dige|chiffre|envoie|publie|supprime|"
                    r"retire|ajoute|corrige|approuve|paie|paye)\b", re.I)


class LearnError(Exception):
    pass


def validate(db: Session, message_id: str) -> LearnedAnswer:
    ans = db.get(Message, message_id)
    if ans is None or ans.role != "assistant" or not (ans.content or "").strip():
        raise LearnError("Message introuvable.")
    if ans.content.startswith(REFUSED_PREFIXES):
        raise LearnError("Cette réponse n'est pas un savoir à retenir.")
    meta = json.loads(ans.meta_json or "{}")
    if (meta.get("structured") or {}).get("documents") or (meta.get("structured") or {}).get("drafts") or meta.get("artifacts"):
        raise LearnError("Un document ou un brouillon n'est pas un savoir à retenir.")
    prev = (db.query(Message).filter(Message.conversation_id == ans.conversation_id, Message.role == "user",
                                     Message.created_at <= ans.created_at).order_by(Message.created_at.desc()).first())
    if prev is None or len(retrieval.useful_words(prev.content)) < MIN_WORDS:
        raise LearnError("Question trop courte pour être retenue.")
    row = db.query(LearnedAnswer).filter(LearnedAnswer.message_id == message_id).first()
    if row is None:
        row = LearnedAnswer(message_id=message_id, question=prev.content[:2000], answer=ans.content[:8000])
        db.add(row)
    db.flush()
    return row


def forget(db: Session, message_id: str) -> None:
    db.query(LearnedAnswer).filter(LearnedAnswer.message_id == message_id).delete()


def validated_ids(db: Session, message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    return {r.message_id for r in db.query(LearnedAnswer.message_id).filter(LearnedAnswer.message_id.in_(message_ids))}


def find(db: Session, question: str) -> LearnedAnswer | None:
    q = retrieval.useful_words(question)
    if len(q) < MIN_WORDS or ACTION.search(question or ""):
        return None
    rows = db.query(LearnedAnswer).all()
    best, best_cov = None, 0.0
    for r in rows:
        cov = len(q & retrieval.useful_words(r.question)) / len(q)
        if cov > best_cov or (cov == best_cov and best is not None and r.created_at > best.created_at):
            best, best_cov = r, cov
    if best is None or best_cov < MIN_COVERAGE:
        return None
    best.hits += 1
    return best


def local_reply(db: Session, question: str) -> str | None:
    """Réponse de secours depuis le savoir validé, avec sa date ; None si rien de fiable."""
    row = find(db, question)
    if row is None:
        return None
    day = row.created_at.strftime("%d/%m/%Y") if row.created_at else "?"
    return f"_Claude est indisponible. Réponse déjà validée par toi le {day} :_\n\n{row.answer}"
