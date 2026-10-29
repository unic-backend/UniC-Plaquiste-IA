"""« note que Moussa a payé 50 000 » : un versement, pas une simple note. Avec l'IA cloud, il part à l'IA qui l'enregistre au bon
endroit (versement, dépense, journée d'ouvrier, agenda) ; avant, il finissait dans la mémoire et le suivi d'argent ne le voyait pas.
« retiens que mon fournisseur de rails est Sococim » reste une note retenue tout de suite."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import orchestrator
from app.config import settings
from app.main import app


@pytest.mark.parametrize("text, event", [
    ("note que Moussa a payé 50 000", True),
    ("retiens que j'ai reçu 200 000 de Awa Fall", True),
    ("retiens que Ibou a travaillé 2 jours chez Diop", True),
    ("souviens-toi que j'ai rendez-vous jeudi à 10 h chez Fall", True),
    ("retiens que mon fournisseur de rails est Sococim", False),
    ("souviens-toi que la TVA est 18 %", False),
])
def test_evenement_ou_note(text, event):
    from app import memory as mem
    assert bool(orchestrator.REMEMBER_EVENT_RE.search(mem.parse_remember(text) or "")) == event


def _fake_claude(monkeypatch, calls):
    from app.ai import ClaudeAIProvider

    def create(**kw):
        calls.append(kw)
        return NS(content=[NS(type="text", text="Versement noté.", citations=None)], stop_reason="end_turn", model="m",
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                           server_tool_use=NS(web_search_requests=0)))
    monkeypatch.setattr(settings, "local_ai_url", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "secret-key")
    monkeypatch.setattr(ClaudeAIProvider, "_client", lambda self: NS(beta=NS(messages=NS(create=create)), messages=NS(create=create)))


def test_un_versement_dit_avec_note_que_part_a_l_ia(monkeypatch):
    calls = []
    _fake_claude(monkeypatch, calls)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"message": "note que Moussa a payé 50 000"}).json()
        assert calls and "Retenu" not in r["message"]["content"]                  # l'IA a la main (record_receipt), pas la mémoire
        calls.clear()
        r = c.post("/api/chat", json={"message": "retiens que mon fournisseur de rails est Sococim"}).json()
        assert r["message"]["content"].startswith("Retenu") and not calls          # une simple note : retenue tout de suite
