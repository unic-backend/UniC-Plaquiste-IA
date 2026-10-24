"""Étape 10 du diagnostic : tâches dans l'agenda, et calendrier du téléphone abonné par un lien secret (.ics)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Appointment


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def _day(delta: int, hm: str = "10:00") -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta)).strftime("%Y-%m-%d ") + hm


def test_une_tache_n_est_jamais_un_conflit_et_reste_visible_si_en_retard(c):
    r = c.post("/api/agenda", json={"title": "Métré salon Fall", "start": _day(3), "kind": "metre", "phone": "+221770000001"})
    assert r.status_code == 200
    t = c.post("/api/agenda", json={"title": "Commander les rails chez Sotiba", "start": _day(3, "10:15"), "kind": "tache"}).json()
    assert t["conflits"] == [] and t["rdv"]["kind_label"] == "À faire"
    with SessionLocal() as db:   # tâche d'hier jamais faite : elle remonte en retard
        db.add(Appointment(title="Relancer M. Ndiaye", kind="tache", start_at=datetime.now(timezone.utc) - timedelta(days=2)))
        db.commit()
    late = c.get("/api/agenda").json()["taches_en_retard"]
    assert any(x["title"] == "Relancer M. Ndiaye" for x in late)


def test_calendrier_du_telephone_par_lien_secret(c):
    assert c.get("/api/agenda/feed").json() == {"enabled": False, "url": "", "webcal": ""}   # coupé tant que le patron n'active pas
    assert c.get("/api/public/agenda/nimportequoi.ics").status_code == 404
    c.post("/api/agenda", json={"title": "Pose plafond Diop; salon, cuisine", "start": _day(5), "kind": "pose",
                                "location": "Médina, rue 11", "client_name": "Awa Diop", "phone": "+221770009999", "notes": "code portail 4321"})
    gone = c.post("/api/agenda", json={"title": "Visite annulée", "start": _day(6), "kind": "visite"}).json()["rdv"]["id"]
    c.patch(f"/api/agenda/{gone}", json={"status": "cancelled"})

    on = c.post("/api/agenda/feed", json={"on": True}).json()
    assert on["enabled"] and on["url"].endswith(".ics") and on["webcal"].startswith("webcal://")
    path = "/" + on["url"].split("/", 3)[3]
    r = c.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Pose plafond Diop\\; salon\\, cuisine" in body.replace("\r\n ", "")       # échappés ; pas de « Pose · Pose »
    assert "Médina" in body and "Awa Diop" in body
    # ni téléphone ni notes (on cherche le texte de la note, pas « 4321 » seul : un identifiant aléatoire peut le contenir)
    assert "+221770009999" not in body and "code portail" not in body
    assert "Visite annulée" not in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))                       # lignes pliées (RFC 5545)

    new = c.post("/api/agenda/feed", json={"on": True}).json()                                # nouveau lien : l'ancien ne marche plus
    assert new["url"] != on["url"] and c.get(path).status_code == 404
    assert c.post("/api/agenda/feed", json={"on": False}).json()["enabled"] is False
    assert c.get("/" + new["url"].split("/", 3)[3]).status_code == 404
