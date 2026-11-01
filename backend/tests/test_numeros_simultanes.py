"""Numéros de client, fournisseur, projet : deux créations en même temps ne reçoivent jamais le même numéro.
Avant : lire la valeur, ajouter 1, écrire. Huit fils × 40 appels donnaient 56 numéros en double et 5 erreurs."""
import os
import sys
import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import services  # noqa: E402
from app.models import Sequence  # noqa: E402


def test_huit_fils_obtiennent_des_numeros_tous_differents(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(conn, _):   # mêmes réglages que app.database : WAL et attente d'un écrivain
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
    Sequence.__table__.create(engine)
    Session = sessionmaker(engine)
    got, errors, lock = [], [], threading.Lock()

    def work():
        for _ in range(25):
            with Session() as db:
                try:
                    n = services.next_number(db, "customer")
                    db.commit()
                except Exception as exc:  # noqa: BLE001 : le test échoue plus bas, avec le détail
                    errors.append(repr(exc))
                    continue
            with lock:
                got.append(n)
    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors[:3]
    assert len(got) == 200 and len(set(got)) == 200
    assert max(got).endswith("-0200")
