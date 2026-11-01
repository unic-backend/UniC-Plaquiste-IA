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


def _outage(messages, tools, tool_handler, **kw):   # Claude injoignable (crédit épuisé) : aucune réponse, aucun outil
    from app.ai import AIResult
    return AIResult("", "claude", kw.get("model", ""), False, "claude: crédit Anthropic épuisé (quota)", error_kind="quota")


def test_une_panne_de_claude_n_est_pas_une_note_de_zero():
    """Le 31/10, le banc affichait 0/31 « outil non appelé » : Claude ne répondait pas. La panne est dite, l'IA n'est pas notée."""
    with SessionLocal() as db:
        before = evals.history(db)
        rep = evals.run(db, cases=evals.CASES[:3], complete=_outage)
        db.commit()
        assert rep["total"] == 0 and rep["unanswered"] == 3 and "crédit Anthropic épuisé" in rep["error"]
        assert all(r.get("unanswered") and r["problems"][0].startswith("Claude n'a pas répondu") for r in rep["results"])
        assert not any("Outil attendu" in p for r in rep["results"] for p in r["problems"])
        assert evals.history(db) == before                                       # la tendance ne chute pas pour une panne
        assert evals.report_last(db)["error"] == rep["error"]                     # l'Atelier affiche la vraie cause
    prev = {"score": 100.0, "results": [{"id": c["id"], "ok": True} for c in evals.CASES[:3]]}
    assert evals.regressions(prev, rep) == []                                    # pas d'alerte « l'IA a empiré »


def test_cas_sans_reponse_mis_a_part_et_reponse_vide_notee():
    from app.ai import AIResult
    first = evals.CASES[0]

    def mixed(messages, tools, tool_handler, **kw):
        if messages[-1]["content"] == first["message"]:
            return _outage(messages, tools, tool_handler, **kw)
        return AIResult("", "claude", "m", False, "empty")                       # Claude a répondu… sans rien faire : c'est noté
    with SessionLocal() as db:
        rep = evals.run(db, cases=evals.CASES[:2], complete=mixed)
        db.rollback()
    assert rep["unanswered"] == 1 and rep["total"] == 1 and rep["passed"] == 0 and "error" not in rep
    noted = next(r for r in rep["results"] if r["id"] == evals.CASES[1]["id"])
    assert not noted.get("unanswered") and any("Outil attendu" in p for p in noted["problems"])
    prev = {"score": 100.0, "results": [{"id": first["id"], "ok": True}]}
    assert not any(first["id"] in m for m in evals.regressions(prev, rep))      # sans réponse : pas « cas qui échoue »


def test_examen_hebdo_impossible_previent_le_patron(monkeypatch):
    seen = []
    monkeypatch.setattr(selfcare, "report", lambda source, message, detail="", kind="error": seen.append((source, message, kind)))
    monkeypatch.setattr(evals, "run", lambda db: {"at": datetime.now(timezone.utc).isoformat(), "score": 0.0, "passed": 0, "total": 0,
                                                  "unanswered": 31, "error": "Claude n'a pas répondu : quota", "results": []})
    monkeypatch.setattr(evals, "report_last", lambda db: {"score": 90.0, "at": "2000-01-01T00:00:00+00:00", "results": []})
    evals.start_background(weekly=True)
    import time
    for _ in range(50):
        if "run" not in evals.RUNNING:
            break
        time.sleep(0.05)
    assert len(seen) == 1 and "Examen de l'IA impossible" in seen[0][1] and "quota" in seen[0][1] and "note en baisse" not in seen[0][1]
