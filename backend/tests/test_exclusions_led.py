"""Un devis avec un ruban LED (plafond à gorge lumineuse, îlot) ne dit plus « Ne sont pas inclus : bandeaux LED » : le client lisait
une contradiction. Les luminaires restent exclus ; sans LED au devis, la mention habituelle ne change pas."""
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import services
from app.database import SessionLocal
from app.main import app
from app.models import Artifact


def _pdf_text(lines):
    with TestClient(app), SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="t", quantities=lines, customer_id=None, project_id=None, user_id=None,
                                               client_name="Awa Fall")
        path = db.get(Artifact, q.artifact_id).path
    return " ".join(p.extract_text() for p in PdfReader(path).pages).replace("\n", " ")


def test_ruban_led_au_devis_pas_exclu():
    text = _pdf_text([{"sku": "UC-COLLE-SILICONE", "name": "Colle silicone", "quantity": 1},
                      {"sku": "UC-RUBAN-LED", "name": "Ruban LED (ml)", "quantity": 14, "unit": "ml"}])
    assert "bandeaux LED" not in text and "ruban LED listé au tableau est compris" in text


def test_sans_led_la_mention_habituelle_reste():
    text = _pdf_text([{"sku": "UC-COLLE-SILICONE", "name": "Colle silicone", "quantity": 1}])
    assert "Luminaires et bandeaux LED" in text
