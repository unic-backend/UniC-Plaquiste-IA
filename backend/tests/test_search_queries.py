"""Recherche de documents et lieux d'un client : le nombre de requêtes ne grandit pas avec le nombre de devis (pas de N+1)."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app import services as svc
from app.database import SessionLocal, engine
from app.main import app
from app.models import Customer, Quotation


@pytest.fixture(scope="module", autouse=True)
def _started():
    with TestClient(app):   # démarrage de l'appli : création des tables
        yield


def _seed(db, n):
    tag = uuid.uuid4().hex[:6]
    for i in range(n):
        c = Customer(code=f"C-{tag}-{i}", name=f"Client{tag}{i}")
        db.add(c)
        db.flush()
        db.add(Quotation(number=f"Q-{tag}-{i}", customer_id=c.id, site_location=f"Lieu {i}", title=f"T{tag}"))
    db.commit()
    return tag


def _count(fn):
    n = {"q": 0}

    def hit(*a, **k):
        n["q"] += 1
    event.listen(engine, "before_cursor_execute", hit)
    try:
        out = fn()
    finally:
        event.remove(engine, "before_cursor_execute", hit)
    return out, n["q"]


def test_search_documents_has_no_n_plus_one():
    db = SessionLocal()
    tag = _seed(db, 12)
    db.expire_all()
    out, q = _count(lambda: svc.search_documents(db, f"Client{tag}", "quote"))
    assert len(out) == 12 and out[0]["client"].startswith(f"Client{tag}")
    assert q <= 3, q
    db.close()


def test_sites_of_client_has_no_n_plus_one():
    db = SessionLocal()
    tag = _seed(db, 12)
    db.expire_all()
    out, q = _count(lambda: svc.sites_of_client(db, f"Client{tag}0"))
    assert out == ["Lieu 0"]
    assert q <= 3, q
    db.close()
