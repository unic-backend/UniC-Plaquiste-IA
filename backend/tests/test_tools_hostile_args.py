"""Outils ajoutés cette nuit : des arguments absurdes (le modèle peut en envoyer) donnent un refus clair, jamais une panne interne."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import agent  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

BAD = [None, "", "abc", -1, 0, 1e999, float("nan"), True, [], {}, [None], {"x": 1}, "€", 10**30, [1, 2], {"libelle": None, "pourcentage": "x"}]
ACTIONS = ["echeancier", "delai", "marge", "comparer", "risque", "concentration_clients"]
FIELDS = ["total", "etapes", "jours_disponibles", "jours_estimes", "jours_risque", "revenu", "couts", "base", "variantes", "facteurs"]


@pytest.fixture(scope="module")
def session():
    with TestClient(app):
        db = SessionLocal()
        yield agent.AgentSession(db, None)
        db.close()


@pytest.mark.parametrize("field", FIELDS)
def test_business_calc_never_internal_error(session, field):
    for value in BAD:
        for action in ACTIONS:
            out = session("business_calc", {"action": action, field: value})
            assert "Erreur interne" not in str(out), (action, field, repr(value))


def test_visit_report_never_internal_error(session):
    for text in BAD:
        for dur in BAD:
            assert "Erreur interne" not in str(session("visit_report", {"texte": text, "duree_secondes": dur})), (repr(text), repr(dur))


def test_risk_with_non_object_factors_explains():
    with TestClient(app):
        db = SessionLocal()
        out = agent.AgentSession(db, None)("business_calc", {"action": "risque", "facteurs": [1, 2]})
        db.close()
    assert out["valide"] is False and "objet" in out["raison"]
