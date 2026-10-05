"""Changement de numéro d'un brouillon : numéro libre exigé, ancien PDF retiré, document approuvé figé."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (enregistre les tables)
from app import revise
from app import services as svc
from app.database import Base
from app.models import Artifact, Quotation


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _quote(db, client="Madame Ribeiro"):
    return svc.quotation_from_quantities(
        db, title="Devis", quantities=[{"name": "Plaque BA13", "quantity": 10, "unit": "u"}],
        customer_id=None, project_id=None, user_id=None, client_name=client, lieu="Ngor Virage")


def test_change_numero_devis_brouillon(db):
    q = _quote(db)
    q.number = "UC-2026-1007-MR"
    db.commit()
    other = Quotation(number="UC-2026-1009-AB", client_label="Awa Ba", status="draft")
    db.add(other)
    db.commit()

    with pytest.raises(revise.ReviseError):   # numéro déjà pris
        revise.revise(db, "quote", q, user_id=None, new_number="UC-2026-1009-AB")
    with pytest.raises(revise.ReviseError):   # format invalide
        revise.revise(db, "quote", q, user_id=None, new_number="UC 2026/1008")

    changes = revise.revise(db, "quote", q, user_id=None, new_number="uc-2026-1008-mr")
    assert q.number == "UC-2026-1008-MR"
    assert any("numéro" in c for c in changes)
    assert revise.find(db, "quote", "UC-2026-1008-MR").id == q.id
    with pytest.raises(revise.ReviseError):
        revise.find(db, "quote", "UC-2026-1007-MR")
    arts = db.query(Artifact).filter(Artifact.entity_id == q.id).all()
    assert len(arts) == 1 and "1008" in arts[0].filename


def test_change_numero_refuse_si_approuve(db):
    q = _quote(db)
    q.status = "approved"
    db.commit()
    with pytest.raises(revise.ReviseError):
        revise.revise(db, "quote", q, user_id=None, new_number="UC-2026-1008-MR")
