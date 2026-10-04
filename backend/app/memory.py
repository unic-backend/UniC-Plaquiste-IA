"""Mémoire durable : l'assistant garde ce que le patron lui apprend, d'une conversation à l'autre.

Sources : ordre explicite (« retiens que… ») ou extraction automatique depuis les
messages DU PATRON uniquement (jamais depuis un e-mail, un avis ou un fichier :
contenus de tiers non fiables). Tout est visible et supprimable dans la page Mémoire.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app import ai
from app.models import Memory

logger = logging.getLogger("unic.memory")

MAX_TEXT = 500
MAX_ITEMS = 400
BLOCK_CHARS = 3500
_WORD = re.compile(r"\w{4,}", re.UNICODE)
REMEMBER_RE = re.compile(
    r"^\s*(?:retiens|retenez|souviens[- ]toi|rappelle[- ]toi|n'oublie pas|notez? bien|notez? que)\s*(?:que|qu'|:)?\s*(.+)$",
    re.I | re.S,
)


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def add(db: Session, text: str, kind: str = "fact", source: str = "user", pinned: bool = False) -> Memory | None:
    """Ajoute un souvenir. Rend None si vide ou déjà connu."""
    text = " ".join(text.split())[:MAX_TEXT]
    if len(text) < 5:
        return None
    key = _norm(text)
    for (existing,) in db.query(Memory.text).all():
        if _norm(existing) == key:
            return None
    if db.query(Memory).count() >= MAX_ITEMS:
        oldest = db.query(Memory).filter(Memory.pinned.is_(False)).order_by(Memory.created_at).first()
        if oldest:
            db.delete(oldest)
    m = Memory(text=text, kind=kind if kind in ("fact", "preference", "correction") else "fact",
               source=source, pinned=pinned)
    db.add(m)
    db.flush()
    return m


_QUOTES = " \t\r\n«»\"“”„‘’'"


def parse_remember(text: str) -> str | None:
    """« Retiens que X » → X, sans guillemets ni ponctuation de bord copiés avec la phrase."""
    m = REMEMBER_RE.match((text or "").lstrip(_QUOTES))
    if not m:
        return None
    return m.group(1).strip(_QUOTES + ".!;,") or None


def block(db: Session, query: str = "", limit_chars: int = BLOCK_CHARS) -> str:
    """Texte injecté dans le prompt : épinglés d'abord, puis les plus pertinents, puis les récents."""
    rows = db.query(Memory).order_by(Memory.created_at.desc()).all()
    if not rows:
        return ""
    words = {w.lower() for w in _WORD.findall(query)}

    def score(m: Memory) -> tuple:
        overlap = len(words & {w.lower() for w in _WORD.findall(m.text)})
        return (m.pinned, overlap, m.created_at)

    lines, used = [], 0
    for m in sorted(rows, key=score, reverse=True):
        line = f"- ({m.kind}) {m.text}"
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "MÉMOIRE UNIC (ce que le patron t'a appris ; fiable, à respecter) :\n" + "\n".join(lines)


def extract_and_store(db: Session, user_text: str) -> list[str]:
    """Extraction automatique depuis un message du patron. Silencieuse en cas d'échec."""
    if len(user_text) < 30 or not ai.provider_chain():
        return []
    try:
        res = ai.chat_complete([
            {"role": "system", "content": (
                "Extrais du message du patron les faits DURABLES qu'il énonce lui-même : préférences, "
                "prix, noms de clients/fournisseurs, méthodes, corrections d'une erreur de l'assistant. "
                "N'invente rien, ne déduis rien, ignore les questions et les calculs ponctuels. "
                'Réponds UNIQUEMENT par un tableau JSON de phrases courtes, ou []. Exemple : ["Le BA13 hydrofuge se pose en salle de bain"]'
            )},
            {"role": "user", "content": user_text[:2000]},
        ], max_tokens=300)
        m = re.search(r"\[.*\]", res.text or "", re.S)
        items = json.loads(m.group(0)) if m else []
    except Exception as exc:  # jamais bloquer la conversation
        logger.debug("extraction mémoire impossible : %s", exc)
        return []
    saved = []
    for it in items[:5]:
        if isinstance(it, str):
            kind = "correction" if re.search(r"\b(non|erreur|faux|corrige)\b", user_text, re.I) else "fact"
            if add(db, it, kind=kind, source="auto"):
                saved.append(it)
    return saved
