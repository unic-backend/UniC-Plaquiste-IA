"""Assemble ce que l'IA doit savoir sur l'entreprise pour CETTE question : base de connaissances et documents reçus.

Recherche BM25 locale ; chaque passage garde sa source (article, fichier, page). Les documents reçus sont des DONNÉES
de tiers : emballés, jamais obéis (voir trust.py).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import retrieval, trust
from app.models import DocumentChunk, KnowledgeArticle, StoredFile

MAX_CHUNKS_SCANNED = 4000


def knowledge_and_documents(db: Session, query: str, articles: int = 3, chunks: int = 4) -> tuple[str, str, int]:
    """(texte base UniC, texte documents, nombre de motifs de manipulation vus dans les documents)."""
    if not retrieval.tokens(query):
        return "", "", 0
    arts = db.query(KnowledgeArticle).all()
    ranked = retrieval.bm25(query, [retrieval.Record(a.id, a.body, a.title) for a in arts])
    by_id = {a.id: a for a in arts}
    kb = "\n\n".join(f"### {by_id[i].title}\n{by_id[i].body[:1500]}" for i, _ in ranked[:articles])

    rows = (db.query(DocumentChunk, StoredFile.filename).join(StoredFile, StoredFile.id == DocumentChunk.file_id)
            .order_by(DocumentChunk.id.desc()).limit(MAX_CHUNKS_SCANNED).all())
    recs = [retrieval.Record(str(c.id), c.text, name) for c, name in rows]
    meta = {str(c.id): (c, name) for c, name in rows}
    docs, flags = [], 0
    for rid, _score in retrieval.bm25(query, recs)[:chunks]:
        c, name = meta[rid]
        wrapped = trust.wrap(c.text[:1200], f"{name}, p. {c.page_number}")
        flags += len(wrapped.suspicions)
        docs.append(wrapped.text)
    return kb, "\n\n".join(docs), flags
