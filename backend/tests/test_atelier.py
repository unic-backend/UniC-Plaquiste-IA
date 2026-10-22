"""Atelier : le banc d'essai mesure la VRAIE IA (consignes, modèle) et compte les actions inventées ; la qualité les montre."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as _NS

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _case(i):
    from app import evals
    return next(c for c in evals.CASES if c["id"] == i)


def test_cas_universels_notes_par_le_code():
    from app import evals
    assert evals.score_case(_case("mail-banque"), [("save_email_draft", {"to": "conseiller@banque.sn", "subject": "x", "body": "y"})])["ok"]
    bad = evals.score_case(_case("mail-sans-adresse"), [("save_email_draft", {"to": "contact@ciment.sn", "subject": "x", "body": "y"})])
    assert not bad["ok"] and "inventé" in bad["problems"][0]                       # une adresse inventée est une invention
    assert evals.score_case(_case("mail-sans-adresse"), [("save_email_draft", {"subject": "Prix", "body": "Bonjour"})])["ok"]
    assert evals.score_case(_case("excel-depenses"), [("make_spreadsheet", {"title": "Dépenses", "sheets": []})])["ok"]
    assert not evals.score_case(_case("pdf-attestation"), [])["ok"]


def test_le_banc_utilise_les_vraies_consignes_et_compte_les_actions_inventees(client):
    from app import agent, evals
    from app.config import settings
    from app.database import SessionLocal
    seen = []

    def fake_complete(messages, tools=None, tool_handler=None, **kw):
        seen.append((messages[0]["content"], kw))
        if "banque" in messages[-1]["content"]:
            tool_handler("save_email_draft", {"to": "conseiller@banque.sn", "subject": "Rendez-vous", "body": "Bonjour"})
            return _NS(text="Brouillon prêt : relis-le puis envoie-le.")
        return _NS(text="J'ai créé le PDF de l'attestation.")                  # aucun outil appelé : action inventée
    with SessionLocal() as db:
        rep = evals.run(db, cases=[_case("mail-banque"), _case("pdf-attestation")], complete=fake_complete)
        db.rollback()
    ok = {r["id"]: r for r in rep["results"]}
    assert ok["mail-banque"]["ok"]
    assert not ok["pdf-attestation"]["ok"] and any("Action inventée" in p for p in ok["pdf-attestation"]["problems"])
    system, kw = seen[0]
    assert agent.AGENT_PROMPT[:60] in system and "AUJOURD'HUI" in system           # mêmes consignes que la conversation
    assert kw["model"] == settings.anthropic_model and kw["effort"] == "high"      # un courrier = enjeu : même modèle qu'en vrai


def test_la_qualite_montre_les_actions_fantomes(client):
    import re
    from app import quality
    from app.database import SessionLocal
    from app.services import audit

    def counts(db):
        row = next(r for r in quality.report(db)["indicateurs"] if r["id"] == "actions_fantomes")
        m = re.match(r"(\d+) rattrapée\(s\) · (\d+) signalée\(s\)", row["valeur"])
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0), row
    with SessionLocal() as db:
        (c0, w0), _ = counts(db)
        audit(db, None, "ai_phantom_claim", "conversation", "c1", "le devis")
        audit(db, None, "ai_phantom_claim", "conversation", "c2", "le rendez-vous")
        audit(db, None, "ai_phantom_warned", "conversation", "c2", "le rendez-vous")
        db.commit()
        (c1, w1), row = counts(db)
    assert (c1 - c0, w1 - w0) == (2, 1) and row["etat"] == "warn"
