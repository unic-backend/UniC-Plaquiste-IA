"""Étape 9 du diagnostic : ce qu'un chantier a coûté et ce qu'il rapporte (dépenses saisies, marge prévue et encaissée)."""
import pytest
from fastapi.testclient import TestClient

from app.agent import AgentSession
from app.claims import unbacked
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, Expense, Quotation, QuotationItem


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def _chantier(c, number: str, who: str, total: float) -> str:
    with SessionLocal() as db:
        q = Quotation(number=number, title="Plafond", client_label=who, status="approved", subtotal=total, total=total, currency="FCFA")
        db.add(q)
        db.flush()
        db.add(QuotationItem(quotation_id=q.id, position=1, description="Faux plafond", quantity=1, unit="u", unit_price=total, total=total))
        db.commit()
        qid = q.id
    assert c.post(f"/api/tracking/quotes/{qid}/decision", json={"decision": "accepted"}).status_code == 200
    return qid


def test_depenses_et_marge_d_un_chantier(c):
    qid = _chantier(c, "UC-DEP-0001-AD", "Aminata Depense", 1_000_000)
    assert c.post("/api/tracking/receipts", json={"quote_id": qid, "amount": 400_000}).status_code == 200
    r = c.post(f"/api/tracking/quotes/{qid}/expenses", json={"label": "20 plaques BA13", "amount": 150_000, "category": "matériaux"})
    assert r.status_code == 200, r.text
    r = c.post(f"/api/tracking/quotes/{qid}/expenses", json={"label": "Paie de 2 ouvriers", "amount": 200_000, "category": "main-d'œuvre"})
    d = r.json()
    assert d["total"] == 350_000 and d["par_categorie"] == {"matériaux": 150_000, "main-d'œuvre": 200_000}   # jamais mélangés
    assert d["marge_prevue"] == 650_000 and d["marge_pct"] == 65.0                      # 1 000 000 − 350 000
    assert d["marge_encaissee"] == 50_000                                                # 400 000 reçus − 350 000
    row = next(x for x in c.get("/api/tracking").json()["chantiers"] if x["id"] == qid)
    assert row["depenses"] == 350_000 and row["marge_prevue"] == 650_000 and row["marge_pct"] == 65.0

    eid = d["lignes"][0]["id"]
    d = c.delete(f"/api/tracking/expenses/{eid}").json()                                  # erreur de saisie : annulée, pas effacée
    assert d["total"] in (150_000, 200_000) and any(x["annulee"] for x in d["lignes"])
    with SessionLocal() as db:
        assert db.get(Expense, eid).status == "cancelled"
        assert db.query(AuditLog).filter_by(action="chantier_expense_cancel").count() >= 1

    for bad in ({"label": "x", "amount": 0}, {"label": "x", "amount": -5}, {"label": "", "amount": 10}):
        assert c.post(f"/api/tracking/quotes/{qid}/expenses", json=bad).status_code in (400, 422)
    assert c.post("/api/tracking/quotes/inconnu/expenses", json={"label": "x", "amount": 10}).status_code == 404


def test_le_chat_note_une_depense_sur_le_bon_chantier(c):
    qid = _chantier(c, "UC-DEP-0002-MS", "Moussa Chantier Sall", 500_000)
    with SessionLocal() as db:
        out = AgentSession(db, None, {})("record_expense", {"amount": 75_000, "label": "Location échafaudage",
                                                            "category": "location", "quote_number": "UC-DEP-0002-MS"})
        assert out["ajoutee"]["montant"] == 75_000 and out["marge_prevue"] == 425_000 and "lignes" not in out
        bad = AgentSession(db, None, {})("record_expense", {"amount": 10, "label": "x", "quote_number": "UC-INEXISTANT"})
        assert "error" in bad
    assert c.get(f"/api/tracking/quotes/{qid}/expenses").json()["par_categorie"] == {"location": 75_000}


@pytest.mark.parametrize("reply, succeeded, expected", [
    ("J'ai noté la dépense de 75 000 FCFA sur le chantier.", ["record_expense"], []),
    ("J'ai noté la dépense de 75 000 FCFA sur le chantier.", [], ["la dépense"]),
])
def test_l_ia_ne_peut_pas_inventer_une_depense(reply, succeeded, expected):
    assert unbacked(reply, succeeded) == expected
