"""Lectures automatiques du chat, testées sur des phrases réelles du patron :
- un nouveau client dit en une phrase est rangé champ par champ (avant : téléphone et quartier finissaient dans le NOM,
  même avec l'exemple affiché dans l'appli) ;
- « mes factures impayées » / « mes clients qui n'ont pas payé » ne montrent plus la liste complète ;
- « le prix d'un plafond de 30 m² » est une estimation (l'IA chiffre), pas la grille des prix ;
- « Bonjour UniC » est une salutation."""
import pytest
from fastapi.testclient import TestClient

from app import orchestrator
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Supplier


@pytest.mark.parametrize("text, name, phone, email, place", [
    ("crée un client Awa Diop 77 123 45 67 à Pikine", "Awa Diop", "77 123 45 67", "", "Pikine"),
    ("Nouveau client : Awa Ndiaye, 77 000 00 00, Almadies", "Awa Ndiaye", "77 000 00 00", "", "Almadies"),
    ("nouveau client Moussa Fall, +221 76 555 44 33, moussa.fall@gmail.com, Thiès", "Moussa Fall", "+221 76 555 44 33",
     "moussa.fall@gmail.com", "Thiès"),
    ("UniC, crée un client Mme Sow à Rufisque", "Mme Sow", "", "", "Rufisque"),
    ("crée un client Clientèle SARL", "Clientèle SARL", "", "", ""),                       # « client » dans le nom : gardé
    ("crée un client FAST GROUP", "FAST GROUP", "", "", ""),
])
def test_un_client_dit_en_une_phrase_est_range_champ_par_champ(text, name, phone, email, place):
    assert orchestrator._party_details(text) == {"name": name, "phone": phone, "email": email, "place": place}


def test_la_fiche_creee_par_le_chat(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app), SessionLocal() as db:
        out = orchestrator._create_named_party(db, "customer", "Nouveau client : Awa Ndiaye, 77 000 00 00, Almadies", None)
        c = db.query(Customer).filter(Customer.name == "Awa Ndiaye").order_by(Customer.created_at.desc()).first()
        assert (c.phone, c.city, c.email) == ("77 000 00 00", "Almadies", "")
        assert "téléphone 77 000 00 00" in out and "Non donnés (rien d'inventé) : e-mail." in out
        orchestrator._create_named_party(db, "supplier", "nouveau fournisseur Sococim 33 849 12 34", None)
        assert db.query(Supplier).filter(Supplier.name == "Sococim").first().phone == "33 849 12 34"
        assert "Indiquez le nom" in orchestrator._create_named_party(db, "customer", "crée un client", None)


@pytest.mark.parametrize("text, intent", [
    ("mes factures impayées", "chat"),
    ("mes clients qui n'ont pas payé", "chat"),
    ("mes factures", "list_invoices"),
    ("liste des clients", "list_customers"),
    ("donne-moi le prix d'un faux plafond de 30 m²", "chat"),
    ("budget pour une cloison de 6 m sur 2,5 m", "chat"),
    ("calcule une cloison de 12 m sur 2,50 m", "calculate"),
    ("prix des plaques BA13", "prices"),
    ("Bonjour UniC", "greeting"),
    ("salut unic ai !", "greeting"),
])
def test_le_chat_comprend_ce_qui_est_vraiment_demande(text, intent):
    assert orchestrator._intent(text, {}) == intent
