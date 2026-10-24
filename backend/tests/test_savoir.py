"""IA plus savante : lecture de pages entières (web_fetch), plus de recherches sur les sujets difficiles, et une bibliothèque de
savoir qui garde ce que l'IA a appris pour s'en resservir."""
import pytest
from fastapi.testclient import TestClient

from app import context, library, research
from app.agent import AgentSession
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setattr(settings, "web_search_enabled", True)
    with TestClient(app):
        yield


class _Resp:
    stop_reason = "end_turn"

    def __init__(self, text):
        class B:
            type = "text"
            citations = None
        B.text = text
        self.content = [B()]
        self.usage = None


def test_la_lecture_de_page_n_est_proposee_qu_aux_modeles_qui_la_permettent(monkeypatch):
    claude = PROVIDERS["claude"]
    seen = []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    # sur la classe (pas sur l'objet partagé) : remis exactement en place après le test, sans gêner les tests suivants
    monkeypatch.setattr(type(claude), "_client", lambda self: object())
    monkeypatch.setattr(type(claude), "_run", lambda self, client, params, handler, used: seen.append(params.get("tools") or []) or _Resp("ok"))
    msgs = [{"role": "user", "content": "Lis https://exemple.sn"}]
    claude.complete(msgs, model="claude-sonnet-5-5", web=True, fetch=True, web_max_uses=6)
    names = {t["name"]: t for t in seen[-1]}
    assert names["web_fetch"]["type"] == "web_fetch_20260209" and names["web_search"]["max_uses"] == 6
    claude.complete(msgs, model="claude-haiku-4-5", web=True, fetch=True)
    assert [t["name"] for t in seen[-1]] == ["web_search"]                     # ancien modèle : recherche seule
    claude.complete(msgs, model="claude-sonnet-5-5", web=False, fetch=True)
    assert seen[-1] == []                                                       # Internet coupé : ni recherche ni lecture


def _fake_claude(monkeypatch, text):
    claude = PROVIDERS["claude"]
    asked = {}

    def complete(self, messages, **kw):
        asked.update(kw, system=messages[0]["content"], user=messages[1]["content"])
        return AIResult(text, "claude", "claude-sonnet-5-5", True, "", raw={"usage": [], "sources": []})
    monkeypatch.setattr(type(claude), "health", lambda self: {"available": True})
    monkeypatch.setattr(type(claude), "complete", complete)
    return asked


def test_une_page_apprise_est_retrouvee_plus_tard(monkeypatch):
    page = ("# Le baobab au Sénégal\n\nLe baobab (Adansonia digitata) est l'arbre emblème du Sénégal. "
            "Son fruit, le pain de singe, sert à préparer le bouye. Certains baobabs dépassent 1 000 ans.")
    asked = _fake_claude(monkeypatch, page)
    with SessionLocal() as db:
        before = library.count(db)
        out = AgentSession(db, None, {})("learn_page", {"url": "https://exemple.sn/baobab"})
        assert out["titre"] == "Le baobab au Sénégal" and out["source"] == "https://exemple.sn/baobab" and "Résume-la" in out["note"]
        assert library.count(db) == before + 1
        _kb, docs, _flags = context.knowledge_and_documents(db, "Quel âge peut avoir un baobab au Sénégal ?")
        assert "1 000 ans" in docs and "pain de singe" in docs                  # le savoir revient dans une autre conversation
    assert asked["fetch"] is True and asked["web"] is True and "DONNÉE" in asked["system"]


def test_page_illisible_ou_adresse_fausse(monkeypatch):
    _fake_claude(monkeypatch, "PAGE ILLISIBLE")
    with SessionLocal() as db:
        assert "pas pu lire" in AgentSession(db, None, {})("learn_page", {"url": "https://exemple.sn/vide"})["error"]
        assert "http" in AgentSession(db, None, {})("learn_page", {"url": "file:///etc/passwd"})["error"]   # jamais une adresse locale
        assert "http" in AgentSession(db, None, {})("learn_page", {"url": "pas une adresse"})["error"]


def test_une_recherche_sourcee_enrichit_la_bibliotheque(monkeypatch):
    claude = PROVIDERS["claude"]
    monkeypatch.setattr(type(claude), "health", lambda self: {"available": True})
    monkeypatch.setattr(type(claude), "complete", lambda self, messages, **kw: AIResult(
        "# Réponse courte\nLe port autonome de Dakar traite environ 20 millions de tonnes par an [1].", "claude", "claude-opus-5-5", True, "",
        raw={"usage": [], "sources": [{"title": "PAD", "url": "https://portdakar.sn"}]}))
    with SessionLocal() as db:
        before = library.count(db)
        research.run(db, "Trafic annuel du port autonome de Dakar")
        assert library.count(db) == before + 1
        _kb, docs, _ = context.knowledge_and_documents(db, "trafic port autonome Dakar tonnes")
        assert "20 millions de tonnes" in docs
