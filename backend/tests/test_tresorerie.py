"""Trésorerie prévisionnelle : solde donné par le patron, mis à jour par ce qui entre et sort ; prévision semaine par semaine
en deux scénarios ; trou prévu sous le seuil = alerte. Calculé sans IA, jamais un chiffre présenté comme sûr."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import claims, team, tresorerie
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Expense, Quotation, Receipt, Worker, WorkEntry, WorkerPayment

NOW = datetime(2031, 9, 10, 10, tzinfo=timezone.utc)


def at(days: int) -> datetime:
    return NOW + timedelta(days=days)


@pytest.fixture
def setup(monkeypatch):
    """Base propre pour la trésorerie : réglages vierges, et seulement les données de ce test (retirées ensuite)."""
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app):
        made: dict[str, list] = {"q": [], "e": [], "r": [], "w": []}
        # isole le calcul des données des autres tests (restes à encaisser, ouvriers) : seuls ceux de ce test comptent
        from app import tracking
        real_tracking, real_team = tracking.overview, team.overview

        def mine(db):
            ov = real_tracking(db)
            return {**ov, "chantiers": [c for c in ov["chantiers"] if c["id"] in made["q"]],
                    "rappels": [r for r in ov["rappels"] if r["numero"].startswith("UC-TRE-")]}
        monkeypatch.setattr(tracking, "overview", mine)
        monkeypatch.setattr(team, "overview", lambda db: {"ouvriers": [], "reste_du_total": sum(
            r["reste_du"] for r in real_team(db)["ouvriers"] if r["id"] in made["w"] and r["reste_du"] > 0)})
        with SessionLocal() as db:
            tresorerie._put(db, {})
            db.commit()
        yield made
        with SessionLocal() as db:
            tresorerie._put(db, {})
            db.query(Receipt).filter(Receipt.quotation_id.in_(made["q"])).delete(synchronize_session=False)
            db.query(Expense).filter(Expense.id.in_(made["e"])).delete(synchronize_session=False)
            db.query(WorkEntry).filter(WorkEntry.worker_id.in_(made["w"])).delete(synchronize_session=False)
            db.query(WorkerPayment).filter(WorkerPayment.worker_id.in_(made["w"])).delete(synchronize_session=False)
            db.query(Worker).filter(Worker.id.in_(made["w"])).delete(synchronize_session=False)
            db.query(Quotation).filter(Quotation.id.in_(made["q"])).delete(synchronize_session=False)
            db.commit()


def _quote(db, made, number, total, collect=None, decided=-20):
    q = Quotation(number=number, title="Plafond", client_label=f"Client {number}", status="approved", total=total, subtotal=total,
                  currency="FCFA", client_decision="accepted", decided_at=at(decided), approved_at=at(decided), created_at=at(decided),
                  collect_on=collect)
    db.add(q)
    db.flush()
    made["q"].append(q.id)
    return q


def _expense(db, made, label, amount, day):
    e = Expense(label=f"TRE {label}", amount=amount, category="matériaux", spent_at=at(day))
    db.add(e)
    db.flush()
    made["e"].append(e.id)


def test_sans_solde_on_montre_les_variations_et_on_le_demande(setup):
    with SessionLocal() as db:
        f = tresorerie.forecast(db, now=NOW)
        assert f["solde"] is None and f["premier_trou"] is None and len(f["semaines"]) == 13
        assert "Donne ton solde" in f["points_attention"][0]
        assert tresorerie.alert(db, now=NOW) == ""                                   # pas d'alerte sans solde


def test_solde_mis_a_jour_et_prevision_en_deux_scenarios(setup):
    made = setup
    with SessionLocal() as db:
        tresorerie.set_balance(db, 1_000_000, now=at(-5))
        tresorerie.set_options(db, charges=[{"libelle": "Loyer atelier", "montant": 300_000, "jour": 15}], seuil=100_000)
        q1 = _quote(db, made, "UC-TRE-1", 2_000_000, collect=at(9))                 # 1,5 M attendus dans 9 jours (rappel)
        db.add(Receipt(quotation_id=q1.id, amount=500_000, received_at=at(-2)))      # entré depuis le solde donné
        _quote(db, made, "UC-TRE-2", 800_000, collect=at(-10))                      # en retard
        _quote(db, made, "UC-TRE-3", 400_000)                                       # sans date
        _expense(db, made, "plaques", 200_000, -1)                                  # sorti depuis le solde donné
        _expense(db, made, "location échafaudage", 150_000, 20)                     # prévue
        worker = Worker(name="Ouvrier Tresorerie Test", pay_mode="jour", day_rate=10_000)
        db.add(worker)
        db.flush()
        made["w"].append(worker.id)
        team.record_work(db, worker, days=3, quote=db.get(Quotation, q1.id))       # 30 000 dus (la dépense main-d'œuvre n'est pas une sortie d'argent)
        made["e"] += [e.id for e in db.query(Expense).filter(Expense.quotation_id == q1.id).all()]
        db.commit()
        f = tresorerie.forecast(db, now=NOW)
    assert f["solde"]["aujourdhui"] == 1_300_000                                    # 1 000 000 + 500 000 − 200 000
    states = {r["numero"]: r["etat"] for r in f["entrees"]}
    assert states == {"UC-TRE-1": "prévu", "UC-TRE-2": "en retard", "UC-TRE-3": "sans date"}
    assert f["sorties"]["ouvriers"] == 30_000
    assert [c["date"] for c in f["sorties"]["charges_fixes"]][:3] == ["2031-09-15", "2031-10-15", "2031-11-15"]
    assert f["sorties"]["prevues"] == [{"date": at(20).date().isoformat(), "montant": 150_000, "libelle": "TRE location échafaudage"}]
    w0, w1 = f["semaines"][0], f["semaines"][1]
    assert w0["sorties"] == 330_000 and w0["entrees_prudent"] == 0                 # ouvriers + loyer du 15
    assert w1["entrees_prudent"] == 1_500_000                                       # le 19/09 (rappel)
    assert w0["solde_prudent"] == 1_300_000 - 330_000 - w0["depenses_courantes"]
    assert f["semaines"][2]["entrees_probable"] == 800_000                           # le retard rentre dans 15 jours (probable seulement)
    assert f["semaines"][4]["entrees_probable"] == 400_000 and f["semaines"][4]["entrees_prudent"] == 0
    assert any("en retard" in p for p in f["points_attention"]) and any("sans date" in p for p in f["points_attention"])


def test_trou_prevu_alerte_et_outils_du_chat(setup):
    made = setup
    with SessionLocal() as db:
        tresorerie.set_balance(db, 200_000, now=NOW)
        tresorerie.set_options(db, charges=[{"libelle": "Salaire secrétaire", "montant": 350_000, "jour": 25}], seuil=0)
        db.commit()
        f = tresorerie.forecast(db, now=NOW)
        assert f["premier_trou"]["semaine_du"] == "2031-09-24" and f["premier_trou"]["solde"] < 0
        msg = tresorerie.alert(db, now=NOW)
        assert "trou prévu dans 14 jours" in msg
        assert tresorerie.daily_alert(db, now=NOW) == msg and tresorerie.daily_alert(db, now=NOW) == ""   # une fois par jour
        s = AgentSession(db, None, {"owner_message": "j'ai 2 500 000 en caisse et banque"})
        out = s("set_cash_balance", {"montant": 2_500_000})
        assert out["solde_enregistre"] == 2_500_000 and out["premier_trou"] is None
        assert claims.unbacked("Solde de trésorerie enregistré : 2 500 000 FCFA.", s.succeeded) == []
        assert "semaines" in s("cash_forecast", {})
    assert claims.unbacked("J'ai mis à jour ta trésorerie.", []) == ["la trésorerie"]       # sans outil : affirmation fantôme


def test_api_et_validation(setup):
    with TestClient(app) as c:
        assert c.get("/api/tresorerie").json()["solde"] is None
        f = c.post("/api/tresorerie/solde", json={"montant": -50_000}).json()               # découvert accepté
        assert f["solde"]["donne"] == -50_000
        f = c.post("/api/tresorerie/reglages", json={"charges": [{"libelle": "Loyer", "montant": 100_000, "jour": 5}], "seuil": 0}).json()
        assert f["charges"] == [{"libelle": "Loyer", "montant": 100_000, "jour": 5}]
        assert c.post("/api/tresorerie/reglages", json={"charges": [{"libelle": "X", "montant": 1, "jour": 40}]}).status_code == 422
        assert c.post("/api/tresorerie/solde", json={"montant": "beaucoup"}).status_code == 422
