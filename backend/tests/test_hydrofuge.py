"""Pièces humides : plaques hydrofuges (référence « -H », 6 000 FCFA la 2 m au catalogue du patron). Avant : seule la lecture de plan
les connaissait ; « faux plafond salle de bain 3x2 » chiffrait la plaque standard."""
import pytest
from fastapi.testclient import TestClient

from app import calc
from app.main import app


def _boards(r):
    return {q.sku: q.quantity for q in r.quantities if q.sku.startswith("BA13-")}


@pytest.mark.parametrize("text, sku, why", [
    ("faux plafond salle de bain 3x2", "BA13-2000x1200-H", "Pièce humide"),
    ("cloison douche 2 x 2,5 une face", "BA13-2000x1200-H", "Pièce humide"),
    ("faux plafond 4x3 hydrofuge", "BA13-2000x1200-H", "demandées"),
    ("cloison de 20 m2 plaques vertes", "BA13-2000x1200-H", "demandées"),
    ("faux plafond 5x4", "BA13-2000x1200", None),
    ("faux plafond cuisine 4x3", "BA13-2000x1200", None),                 # cuisine : pas supposée humide
])
def test_plaques_hydrofuges(text, sku, why):
    r = calc.calculate_from_text(text)
    assert set(_boards(r)) == {sku} and r.to_dict()["verification"]["ok"]
    if why:
        assert r.inputs["hydrofuge"] and any(why in a for a in r.assumptions) and "hydrofuge" in r.quantities[0].name


@pytest.mark.parametrize("text", ["faux plafond salon 5x4 et salle de bain 3x2", "salle de bain 3x2 et cuisine 4x3 en faux plafond"])
def test_pieces_melangees_demande_lesquelles(text):
    r = calc.calculate_from_text(text)
    assert "hydrofuge" not in r.inputs and any("Pièce humide citée" in m for m in r.missing)


def test_decor_en_salle_de_bain_aussi_hydrofuge():
    r = calc.calculate_from_text("faux plafond sdb 3 x 2 avec caisson")
    assert all(s.endswith("-H") for s in _boards(r)) and any("retombées" in q.name for q in r.quantities if q.sku.endswith("-H"))


def test_l_ia_chiffre_la_plaque_hydrofuge_au_devis():
    from app.agent import AgentSession
    from app.database import SessionLocal
    from app.models import Quotation, QuotationItem
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "partition", "length_m": 3, "height_m": 2.5, "sides": 1, "hydrofuge": True})
        assert out["verification"]["ok"] and any(q["sku"] == "BA13-2000x1200-H" for q in out["quantites"])
        quote = s("create_quote", {"client_name": "Awa Fall", "checks": "client, cloison 3x2,5 une face hydrofuge vérifiés",
                                   "objet": "Fourniture et pose d'une cloison BA13 hydrofuge en salle de bain."})
        qid = db.query(Quotation).filter(Quotation.number == quote["numero"]).one().id
        price = next(i.unit_price for i in db.query(QuotationItem).filter(QuotationItem.quotation_id == qid) if "hydrofuge" in i.description)
        assert price == 6000                                                 # prix du patron, pas celui de la plaque standard
