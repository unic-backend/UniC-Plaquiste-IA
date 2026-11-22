"""Règle du patron (22/11/2026) : « Ne sont pas inclus » n'apparaît JAMAIS d'office sur un devis (une liste toute faite disait
« électricité » exclue alors qu'un forfait électricité était au devis). Seulement la liste qu'il demande, et il peut la retirer."""
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import revise, services
from app.database import SessionLocal
from app.main import app
from app.models import Artifact


def _text(db, q):
    return " ".join(p.extract_text() for p in PdfReader(db.get(Artifact, q.artifact_id).path).pages).replace("\n", " ")


def _quote(db, lines, **kw):
    return services.quotation_from_quantities(db, title="t", quantities=lines, customer_id=None, project_id=None, user_id=None,
                                              client_name="Awa Fall", **kw)


def test_aucune_liste_par_defaut_meme_avec_electricite_ou_led():
    with TestClient(app), SessionLocal() as db:
        q = _quote(db, [{"sku": "UC-RUBAN-LED", "name": "Ruban LED (ml)", "quantity": 14, "unit": "ml"},
                        {"name": "Électricité : forfait 4 prises", "quantity": 1, "unit": "forfait", "fixed_price": 300000}])
        text = _text(db, q)
    assert "Ne sont pas inclus" not in text and "électricité, de plomberie" not in text and "Conditions" in text


def test_liste_demandee_imprimee_puis_retiree():
    with TestClient(app), SessionLocal() as db:
        q = _quote(db, [{"sku": "UC-COLLE-SILICONE", "name": "Colle silicone", "quantity": 1}], exclusions=["Peinture", "Portes"])
        text = _text(db, q)
        assert "Ne sont pas inclus" in text and "Peinture" in text and "Portes" in text
        assert services.exclusions_of(q.notes) == ["Peinture", "Portes"]
        revise.revise(db, "quote", q, user_id=None, non_inclus=[])
        db.commit()
        assert "Ne sont pas inclus" not in _text(db, q) and services.exclusions_of(q.notes) == []
