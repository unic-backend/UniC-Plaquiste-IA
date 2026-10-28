"""Noms de clients écrits comme le patron le veut : « Moussa Ba », jamais « moussa ba ». Un nom tapé ou dicté en minuscules est
repris (avant : le devis sortait sans client, numéro en « XXX ») et mis en forme sur le devis, la fiche client et le bon ; un nom
déjà écrit en majuscules (« FAST GROUP ») reste tel quel ; un mot courant (« pour le salon », « pour demain ») n'est jamais un client."""
import pytest
from fastapi.testclient import TestClient

from app import orchestrator
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Quotation
from app.services import nom_propre


@pytest.mark.parametrize("raw, nice", [
    ("moussa ba", "Moussa Ba"),
    ("  awa   ndiaye ", "Awa Ndiaye"),
    ("mame diarra n'diaye", "Mame Diarra N'Diaye"),
    ("abdou-karim fall", "Abdou-Karim Fall"),
    ("jean de la fontaine", "Jean de la Fontaine"),
    ("Ousmane Diop", "Ousmane Diop"),
    ("FAST GROUP", "FAST GROUP"),             # écrit en majuscules par le patron : gardé
    ("McDonald", "McDonald"),
    ("", ""),
])
def test_nom_propre(raw, nice):
    assert nom_propre(raw) == nice


@pytest.mark.parametrize("text, name", [
    ("fais le devis pour moussa ba", "Moussa Ba"),
    ("fais le devis cloison 4 x 2,5 pour moussa ba", "Moussa Ba"),
    ("devis pour mame diarra n'diaye cloison 3x2,5", "Mame Diarra N'Diaye"),
    ("devis pour madame awa fall", "Awa Fall"),
    ("devis client abdou-karim fall", "Abdou-Karim Fall"),
    ("devis pour Ousmane Diop", "Ousmane Diop"),
    ("devis pour le salon de moussa", None),   # jamais un mot courant
    ("fais le devis pour demain", None),
    ("devis pour la villa", None),
    ("devis pour ce client", None),
    ("devis pour moussa", None),               # en minuscules : prénom ET nom, sinon pas deviné
])
def test_nom_du_client_dans_la_phrase(text, name):
    assert orchestrator._client_name_in(text) == name


def test_devis_et_fiche_client_au_bon_format():
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"message": "cloison 4 x 2,5 une face, fais le devis pour moussa ba"}).json()
        qid = r["message"]["meta"]["structured"]["quotation_id"]
        with SessionLocal() as db:
            q = db.get(Quotation, qid)
            assert q.client_label == "Moussa Ba" and q.number.endswith("-MB")      # avant : « XXX », sans client
        assert c.post("/api/customers", json={"name": "awa ndiaye", "contact_name": "ibou sy"}).json()["name"] == "Awa Ndiaye"
        c.post("/api/chat", json={"message": "crée un client fatou sow 77 123 45 67 à Pikine"})
        with SessionLocal() as db:
            assert db.query(Customer).filter(Customer.name == "Fatou Sow").count() == 1


def test_l_ia_ecrit_aussi_le_nom_au_bon_format():
    from app.agent import AgentSession
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        s("calculate_materials", {"kind": "partition", "length_m": 5, "height_m": 2.5, "sides": 2})
        ok = s("create_quote", {"client_name": "khady diouf", "checks": "client, dimensions 5x2,5 et TVA vérifiés",
                                "objet": "Fourniture et pose de cloisons sèches BA13."})
        assert "KD" in ok["numero"]
        assert db.query(Quotation).filter(Quotation.number == ok["numero"]).one().client_label == "Khady Diouf"
