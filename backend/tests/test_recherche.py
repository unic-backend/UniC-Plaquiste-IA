"""Étape 12 du diagnostic : recherche approfondie sourcée, rangée en PDF ; sans source, le rapport est marqué non vérifié."""
import pytest
from fastapi.testclient import TestClient

from app import research
from app.agent import AgentSession
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Artifact, UsageLog


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setattr(settings, "web_search_enabled", True)
    with TestClient(app):
        yield


def _fake(monkeypatch, text, sources):
    seen = {}
    claude = PROVIDERS["claude"]

    def complete(self, messages, **kw):
        seen.update(kw, system=messages[0]["content"], user=messages[1]["content"])
        return AIResult(text, "claude", "claude-opus-5-5", True, "", raw={"usage": [{"input": 1000, "output": 500, "cache_read": 0,
                                                                                    "cache_write": 0, "web": 8}], "sources": sources})
    # sur la classe (pas sur l'objet partagé) : remis exactement en place, sans masquer les tests suivants
    monkeypatch.setattr(type(claude), "health", lambda self: {"available": True})
    monkeypatch.setattr(type(claude), "complete", complete)
    return seen


def test_rapport_source_range_en_pdf_et_compte(monkeypatch):
    srcs = [{"title": "ANSD — prix du ciment", "url": "https://ansd.sn/ciment"}, {"title": "Sococim", "url": "https://sococim.sn"}]
    seen = _fake(monkeypatch, "# Réponse courte\nLe sac de ciment coûte environ 4 000 FCFA [1].", srcs)
    with SessionLocal() as db:
        n_usage = db.query(UsageLog).count()
        out = AgentSession(db, None, {})("deep_research", {"question": "Prix du ciment à Dakar en 2026 selon les fournisseurs"})
        assert out["verifie"] is True and out["nb_sources"] == 2 and "4 000 FCFA [1]" in out["rapport"]
        assert "[1] ANSD — prix du ciment — https://ansd.sn/ciment" in out["rapport"] and "ne rajoute AUCUN chiffre" in out["note"]
        assert db.query(UsageLog).count() == n_usage + 1                                # consommation comptée
        assert db.query(Artifact).filter(Artifact.filename.like("%Recherche%")).count() >= 1
    assert seen["web"] is True and seen["web_max_uses"] == research.MAX_SEARCHES and seen["sources_raw"] is True
    assert "n'invente RIEN" in seen["system"] and "Prix du ciment" in seen["user"]


def test_sans_source_le_rapport_est_marque_non_verifie(monkeypatch):
    _fake(monkeypatch, "# Réponse courte\nJe pense que le marché grandit.", [])
    with SessionLocal() as db:
        out = AgentSession(db, None, {})("deep_research", {"question": "Évolution du marché du placo au Sénégal"})
    assert out["verifie"] is False and "aucune source" in out["rapport"].lower() and "AUCUNE source" in out["note"]


def test_question_vide_ou_recherche_coupee(monkeypatch):
    _fake(monkeypatch, "x", [])
    with SessionLocal() as db:
        assert "error" in AgentSession(db, None, {})("deep_research", {"question": "placo"})
        monkeypatch.setattr(settings, "web_search_enabled", False)
        out = AgentSession(db, None, {})("deep_research", {"question": "Quels fournisseurs de rails à Dakar ?"})
        assert "error" in out and "coupée" in out["error"]
