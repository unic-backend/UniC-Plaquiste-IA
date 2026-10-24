"""Étape 11 du diagnostic : l'IA passe un examen chaque semaine (si le patron l'active) ; ce qui empire le prévient."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import agent, evals, selfcare
from app.config import settings
from app.database import SessionLocal
from app.main import app


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def test_chaque_cas_vise_un_outil_qui_existe():
    names = {t["name"] for t in agent.TOOLS}
    assert all(case["tool"] in names for case in evals.CASES)
    assert {"facture-emise", "depense-chantier", "versement", "tache", "video-chat"} <= {c["id"] for c in evals.CASES}


def test_examen_hebdomadaire_coupe_par_defaut_puis_du_tous_les_7_jours(c):
    with SessionLocal() as db:
        evals.set_weekly(db, False)
        db.commit()
        assert not evals.weekly_due(db)                                         # coupé : jamais de jetons dépensés sans le patron
    assert c.post("/api/evals/weekly", json={"on": True}).json() == {"weekly": True}
    d = c.get("/api/evals").json()
    assert d["weekly"] is True and isinstance(d["history"], list)
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        evals._put(db, evals.SETTING_KEY, '{"at": "%s", "score": 100, "passed": 1, "total": 1, "results": []}' % (now - timedelta(days=2)).isoformat())
        db.commit()
        assert not evals.weekly_due(db, now)                                    # examen d'il y a 2 jours : pas encore
        assert evals.weekly_due(db, now + timedelta(days=6))                    # 8 jours : c'est le moment
    c.post("/api/evals/weekly", json={"on": False})


def test_ce_qui_empire_est_signale():
    prev = {"score": 100.0, "results": [{"id": "a", "ok": True}, {"id": "b", "ok": True}]}
    same = {"score": 100.0, "results": [{"id": "a", "ok": True, "problems": []}, {"id": "b", "ok": True, "problems": []}]}
    assert evals.regressions(prev, same) == []
    worse = {"score": 50.0, "results": [{"id": "a", "ok": True, "problems": []},
                                        {"id": "b", "ok": False, "problems": ["sides inventé (2) alors que le patron ne l'a pas donné."]}]}
    msgs = evals.regressions(prev, worse)
    assert any("50.0 %" in m and "100.0 %" in m for m in msgs) and any("b" in m and "passaient" in m for m in msgs)
    assert any("invente" in m for m in msgs)


def test_examen_hebdo_garde_l_historique_et_previent(monkeypatch):
    def fake_complete(messages, tools, tool_handler, **kw):   # l'IA « oublie » d'appeler l'outil : échec net
        class R:
            text = "D'accord."
        return R()
    with SessionLocal() as db:
        before = len(evals.history(db))
        evals.run(db, cases=evals.CASES[:2], complete=fake_complete)
        db.commit()
        hist = evals.history(db)
        assert len(hist) == min(before + 1, evals.HISTORY_MAX) and hist[-1]["passed"] == 0 and hist[-1]["total"] == 2
    seen = []
    monkeypatch.setattr(selfcare, "report", lambda source, message, detail="", kind="error": seen.append((source, message, kind)))
    monkeypatch.setattr(evals, "run", lambda db: {"at": datetime.now(timezone.utc).isoformat(), "score": 0.0, "passed": 0, "total": 1,
                                                  "results": [{"id": "cloison-320", "ok": False, "problems": ["x"]}]})
    monkeypatch.setattr(evals, "report_last", lambda db: {"score": 100.0, "at": "2000-01-01T00:00:00+00:00",
                                                          "results": [{"id": "cloison-320", "ok": True}]})
    evals.start_background(weekly=True)
    import time
    for _ in range(50):
        if "run" not in evals.RUNNING:
            break
        time.sleep(0.05)
    assert len(seen) == 1 and seen[0][0].startswith("examen IA ") and "-S" in seen[0][0] and seen[0][2] == "check"
    assert "note en baisse" in seen[0][1] and "cloison-320" in seen[0][1]
