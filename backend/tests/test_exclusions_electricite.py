"""Demande du patron : l'électricité ne figure plus dans « Ne sont pas inclus ». Les autres exclusions restent."""
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import metier, services
from app.database import SessionLocal
from app.main import app
from app.models import Artifact


def test_filtre_retire_l_electricite_seulement():
    items = ["Électricité et plomberie.", "Luminaires et bandeaux LED.", "Électricité.", "Peinture, électricité, climatisation."]
    assert metier.sans_electricite(items) == ["Plomberie.", "Luminaires et bandeaux LED.", "Peinture et climatisation."]


def test_exclusions_sans_electricite():
    assert not any("lectri" in x.lower() for x in metier.exclusions())


def test_devis_pdf_sans_electricite():
    with TestClient(app), SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="t", quantities=[{"sku": "UC-COLLE-SILICONE", "name": "Colle silicone",
                                                                       "quantity": 1}],
                                               customer_id=None, project_id=None, user_id=None, client_name="Awa Fall")
        path = db.get(Artifact, q.artifact_id).path
    text = " ".join(p.extract_text() for p in PdfReader(path).pages).replace("\n", " ").lower()
    assert "ne sont pas inclus" in text and "lectricit" not in text
