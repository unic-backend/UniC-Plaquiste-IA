"""Étape 13 (deuxième partie) : équipe et paie — journées, tâches, avances, reste dû ; la journée compte en main-d'œuvre du chantier."""
import pytest
from fastapi.testclient import TestClient

from app.agent import AgentSession
from app.claims import unbacked
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Expense, Quotation, QuotationItem


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


def test_journees_avances_paie_et_reste_du(c):
    qid = _chantier(c, "UC-EQP-0001-FD", "Fatou Equipe Diallo", 900_000)
    w = c.post("/api/team/workers", json={"name": "Moussa Ndiaye Equipe", "pay_mode": "jour", "day_rate": 15000, "role": "plaquiste"}).json()
    assert c.post("/api/team/workers", json={"name": "moussa  ndiaye equipe"}).status_code == 400          # pas de doublon
    d = c.post(f"/api/team/workers/{w['id']}/work", json={"days": 2.5, "quote_id": qid, "label": "Pose plafond"}).json()
    assert d["travail"] == 37500 and d["journees"] == 2.5                                                  # 2,5 × 15 000
    d = c.post(f"/api/team/workers/{w['id']}/work", json={"amount": 20000, "label": "Bandes du couloir"}).json()
    assert d["travail"] == 57500
    d = c.post(f"/api/team/workers/{w['id']}/payments", json={"amount": 10000, "kind": "avance", "method": "Wave"}).json()
    d = c.post(f"/api/team/workers/{w['id']}/payments", json={"amount": 30000, "kind": "paie"}).json()
    assert d["avances"] == 10000 and d["paye"] == 30000 and d["reste_du"] == 17500                         # 57 500 − 10 000 − 30 000
    exp = c.get(f"/api/tracking/quotes/{qid}/expenses").json()                                             # le chantier voit la main-d'œuvre
    assert exp["par_categorie"] == {"main-d'œuvre": 37500} and exp["marge_prevue"] == 862500
    work_id = next(h["id"] for h in d["historique"] if h["sorte"] == "travail" and h["chantier"] == "UC-EQP-0001-FD")
    d = c.delete(f"/api/team/entries/{work_id}").json()                                                    # erreur : annulée, pas effacée
    assert d["travail"] == 20000 and d["reste_du"] == -20000
    assert c.get(f"/api/tracking/quotes/{qid}/expenses").json()["total"] == 0                              # dépense du chantier annulée aussi
    with SessionLocal() as db:
        assert db.query(Expense).filter_by(quotation_id=qid, status="cancelled").count() == 1
    assert c.get("/api/team").json()["ouvriers"][0]["nom"]


def test_jamais_de_tarif_devine_et_le_chat_note_le_travail(c):
    qid = _chantier(c, "UC-EQP-0002-AS", "Aliou Equipe Sow", 500_000)
    tache = c.post("/api/team/workers", json={"name": "Ibrahima Tache Fall", "pay_mode": "tache"}).json()
    r = c.post(f"/api/team/workers/{tache['id']}/work", json={"days": 1})
    assert r.status_code == 400 and "je ne le devine pas" in r.json()["detail"]
    c.post("/api/team/workers", json={"name": "Cheikh Jour Gaye", "pay_mode": "jour", "day_rate": 12000})
    with SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("record_work", {"worker": "cheikh gaye", "days": 2, "quote_number": "UC-EQP-0002-AS"})
        assert out["ajoute"]["montant"] == 24000 and out["ajoute"]["chantier"] == "UC-EQP-0002-AS" and "historique" not in out
        out = s("record_worker_payment", {"worker": "Cheikh Jour Gaye", "amount": 30000, "kind": "avance"})
        assert out["reste_du"] == -6000 and "avance à récupérer" in out["attention"]
        assert "error" in s("record_work", {"worker": "Personne Inconnue", "days": 1})
        assert s("team_status", {})["reste_du_total"] >= 0
    assert c.get(f"/api/tracking/quotes/{qid}/expenses").json()["par_categorie"] == {"main-d'œuvre": 24000}


@pytest.mark.parametrize("reply, succeeded, expected", [
    ("J'ai noté la paie de Moussa : 30 000 FCFA.", ["record_worker_payment"], []),
    ("J'ai noté la paie de Moussa : 30 000 FCFA.", [], ["la paie de l'ouvrier"]),
    ("J'ai enregistré l'avance de 10 000 à Moussa.", ["record_worker_payment"], []),
])
def test_l_ia_ne_peut_pas_inventer_une_paie(reply, succeeded, expected):
    assert unbacked(reply, succeeded) == expected
