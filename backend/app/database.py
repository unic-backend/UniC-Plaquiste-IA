from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


connect_args = {}
if settings.is_sqlite:
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SLOW_QUERY_MS = 200
SLOW_QUERIES: deque = deque(maxlen=50)   # dernières requêtes lentes : texte SQL seulement, jamais les valeurs


@event.listens_for(engine, "before_cursor_execute")
def _query_start(conn, cursor, statement, parameters, context, executemany):
    context._query_start = time.perf_counter()   # sur le contexte d'exécution : une requête en erreur ne laisse rien derrière


@event.listens_for(engine, "after_cursor_execute")
def _query_end(conn, cursor, statement, parameters, context, executemany):
    ms = (time.perf_counter() - getattr(context, "_query_start", time.perf_counter())) * 1000
    if ms >= SLOW_QUERY_MS:
        SLOW_QUERIES.append({"ms": round(ms), "sql": " ".join(statement.split())[:300],
                             "at": datetime.now(timezone.utc).isoformat()})


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns(eng=None) -> None:
    """Ajoute les colonnes récentes manquantes (bases créées avant leur ajout). Additif uniquement."""
    from sqlalchemy import inspect, text

    eng = eng or engine
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=eng.dialect)
                default = ""
                arg = col.default.arg if col.default is not None else None
                if isinstance(arg, bool):
                    default = f" DEFAULT {('TRUE' if arg else 'FALSE') if eng.dialect.name == 'postgresql' else (1 if arg else 0)}"
                elif isinstance(arg, (int, float)):
                    default = f" DEFAULT {arg}"
                elif isinstance(arg, str):
                    default = " DEFAULT '" + arg.replace("'", "''") + "'"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{default}'))


def ensure_indexes(eng=None) -> int:
    """Crée les index déclarés dans les modèles qui manquent sur une base existante (ajout seulement, aucune donnée touchée)."""
    from sqlalchemy import inspect

    eng = eng or engine
    insp = inspect(eng)
    made = 0
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {i["name"] for i in insp.get_indexes(table.name)}
        for idx in table.indexes:
            if idx.name not in have:
                idx.create(bind=eng, checkfirst=True)
                made += 1
    return made
