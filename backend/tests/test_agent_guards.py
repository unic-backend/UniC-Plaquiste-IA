"""Garde-fous des agents automatiques : appliqués par le SERVEUR, jamais par le modèle."""
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agents  # noqa: E402
from app.ai import AIResult  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client):
    from app.database import SessionLocal
    s = SessionLocal()
    agents.set_halt(s, False)
    yield s
    agents.set_halt(s, False)
    s.close()


def _agent(db, name, tools=None):
    a = agents.create(db, name, "Chaque matin, liste les factures en retard et prépare les rappels.", 24, by="owner", active=True, tools=tools)
    return a


def _ok(text="Rien à signaler."):
    return AIResult(text, "claude", "test", True)


def test_agent_tool_list_can_only_shrink_never_grow(db):
    narrow = _agent(db, "Agent liste étroite", tools=["list_unpaid", "list_agenda"])
    assert agents.tools_for(narrow) == {"list_unpaid", "list_agenda"}
    default = _agent(db, "Agent liste par défaut")
    assert agents.tools_for(default) == agents.SAFE_TOOLS
    with pytest.raises(agents.AgentError, match="refusé"):
        _agent(db, "Agent trop puissant", tools=["list_unpaid", "create_quote"])           # outil d'écriture : refusé à la création
    narrow.allowed_tools = '["create_quote", "list_unpaid"]'                                # liste falsifiée en base : l'intersection protège
    assert agents.tools_for(narrow) == {"list_unpaid"}
    from app.agent import AgentSession
    out = AgentSession(db, None, {"owner_message": "crée un agent"})("create_agent", {"name": "Agent IA outils", "mission": "Lis les mails chaque matin pour préparer des brouillons.",
                                                                                         "every_hours": 24, "owner_asked": True, "tools": ["record_receipt"]})
    assert "refusé" in out["error"]                                                          # l'IA ne peut pas s'accorder un outil d'écriture


def test_run_control_refuses_forbidden_tools_loops_call_caps_and_emergency_stop(db):
    ctl = agents.RunControl("r1", {"list_unpaid"})
    assert ctl.check(db, "create_quote", {}) == "Outil non autorisé pour cet agent."        # hors liste
    assert ctl.check(db, "list_unpaid", {"a": 1}) is None and ctl.check(db, "list_unpaid", {"a": 1}) is None
    assert "boucle détectée" in ctl.check(db, "list_unpaid", {"a": 1})                       # 3e fois le même appel
    assert "termine maintenant" in ctl.check(db, "list_unpaid", {"a": 2})                    # une fois arrêté, tout est refusé
    ctl2 = agents.RunControl("r2", {"list_unpaid"})
    for i in range(agents.MAX_TOOL_CALLS):
        assert ctl2.check(db, "list_unpaid", {"i": i}) is None
    assert "plafond" in ctl2.check(db, "list_unpaid", {"i": 99})
    ctl3 = agents.RunControl("r3", {"list_unpaid"}, max_seconds=-1)
    assert "durée maximale" in ctl3.check(db, "list_unpaid", {})
    ctl4 = agents.RunControl("r4", {"list_unpaid"})
    agents.set_halt(db, True)
    assert "arrêt d'urgence" in ctl4.check(db, "list_unpaid", {})


def test_agent_run_is_journaled_with_a_correlation_id_and_stops_on_loops(db, monkeypatch):
    a = _agent(db, "Agent boucle test", tools=["list_unpaid"])

    def looping(msgs, tools=None, tool_handler=None, **kw):
        seen = [tool_handler("list_unpaid", {}), tool_handler("list_unpaid", {}), tool_handler("list_unpaid", {}),
                tool_handler("create_quote", {})]                                            # 3e identique = boucle ; create_quote jamais autorisé
        assert "error" in seen[2] and "error" in seen[3]
        return _ok("Rapport après boucle.")
    monkeypatch.setattr(agents, "_complete", looping)
    out = agents.run(db, a)
    assert out["ok"] and out["arret"].startswith("boucle détectée") and out["rapport"].startswith("⚠️ Passage interrompu")
    db.refresh(a)
    assert a.last_run_id == out["run_id"] and len(a.last_run_id) == 12
    events = agents.journal(db, a)
    actions = [e["action"] for e in events]
    assert actions.count("agent_tool") == 2 and "agent_tool_refused" in actions and actions[-1] == "agent_run"
    assert all(e["detail"].startswith(f"run={a.last_run_id}") for e in events)              # tout est relié par le même identifiant


def test_agent_hard_time_limit_stops_a_stuck_run(db, monkeypatch):
    a = _agent(db, "Agent bloqué test", tools=["list_unpaid"])
    monkeypatch.setattr(agents, "MAX_SECONDS", 0.2)
    monkeypatch.setattr(agents, "GRACE_SECONDS", 0.2)
    release = {"go": False}

    def stuck(msgs, tools=None, tool_handler=None, **kw):
        t0 = time.time()
        while not release["go"] and time.time() - t0 < 3:
            time.sleep(0.05)
        return _ok("trop tard")
    monkeypatch.setattr(agents, "_complete", stuck)
    t0 = time.time()
    out = agents.run(db, a)
    assert time.time() - t0 < 2.5 and not out["ok"] and "durée maximale dépassée" in out["rapport"]
    release["go"] = True
    db.refresh(a)
    assert a.last_ok is False and "durée maximale" in a.last_result


def test_emergency_stop_blocks_every_start_and_stops_a_run_in_progress(db, client, monkeypatch):
    a = _agent(db, "Agent arrêt urgence", tools=["list_unpaid"])
    assert client.post("/api/agents/halt").json() == {"halted": True}
    assert client.get("/api/selfcare").json()["agents_halted"] is True
    assert agents.run_due(db) == []                                                          # l'horloge ne démarre rien
    assert agents.start(a.id) is False                                                       # ni un démarrage manuel
    assert client.post(f"/api/agents/{a.id}/run").json()["started"] is False
    client.post("/api/agents/resume")
    assert client.get("/api/selfcare").json()["agents_halted"] is False

    def mid_run(msgs, tools=None, tool_handler=None, **kw):
        first = tool_handler("list_unpaid", {})
        agents.set_halt(db, True)                                                            # le patron appuie sur l'arrêt d'urgence pendant le passage
        second = tool_handler("list_agenda", {})
        assert "error" not in first and "arrêt d'urgence" in second["error"]
        return _ok("Rapport partiel.")
    monkeypatch.setattr(agents, "_complete", mid_run)
    out = agents.run(db, _agent(db, "Agent arrêt en cours", tools=["list_unpaid", "list_agenda"]))
    assert out["arret"] == "arrêt d'urgence du patron" and "interrompu" in out["rapport"]
    j = client.get(f"/api/agents/{db.query(agents.CustomAgent).filter_by(name='Agent arrêt en cours').one().id}/journal").json()
    assert j["run_id"] == out["run_id"] and any(e["action"] == "agent_tool_refused" for e in j["events"])
