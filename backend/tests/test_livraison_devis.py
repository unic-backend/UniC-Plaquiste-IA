"""Règle du patron (V9) : la livraison fait partie du tableau des matériaux et s'écrit « Livraison : à la charge du client »
(0 FCFA, 1 forfait), sauf s'il donne un prix. Avant : règle seulement en mémoire, l'IA l'oubliait (leçon déjà notée par le patron)."""
from fastapi.testclient import TestClient

from app import services
from app.database import SessionLocal
from app.main import app
from app.models import QuotationItem


def _items(db, qid):
    return sorted(db.query(QuotationItem).filter(QuotationItem.quotation_id == qid), key=lambda i: i.position)


def test_chaque_devis_porte_la_livraison_a_la_charge_du_client():
    with TestClient(app), SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="t", quantities=[{"sku": "UC-COLLE-SILICONE", "name": "Colle silicone", "quantity": 2}],
                                               customer_id=None, project_id=None, user_id=None, client_name="Awa Fall")
        items = _items(db, q.id)
        assert [i.description for i in items] == ["Colle silicone", "Livraison : à la charge du client"]
        assert (items[-1].quantity, items[-1].unit, items[-1].unit_price, items[-1].total) == (1, "forfait", 0, 0)
        assert q.prices_complete and q.subtotal == items[0].total                 # 0 FCFA : le total ne bouge pas


def test_une_livraison_deja_donnee_n_est_pas_doublee():
    with TestClient(app), SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="t", quantities=[{"name": "Colle silicone", "sku": "UC-COLLE-SILICONE", "quantity": 1},
                                                                          {"name": "Livraison Pikine", "quantity": 1, "unit": "forfait"}],
                                               customer_id=None, project_id=None, user_id=None, client_name="Awa Fall")
        assert sum("ivraison" in i.description for i in _items(db, q.id)) == 1
