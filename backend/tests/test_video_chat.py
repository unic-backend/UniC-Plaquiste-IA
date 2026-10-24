"""Étape 8 du diagnostic : une vidéo se demande dans le chat. L'IA écrit le scénario et le range dans le Studio vidéo ;
la fabrication reste un clic du patron, et l'IA ne peut pas dire que la vidéo est faite."""
import pytest
from fastapi.testclient import TestClient

from app import main, repair, video_studio
from app.agent import AgentSession
from app.claims import unbacked
from app.config import settings
from app.database import SessionLocal

FAKE = {"spec": {"format": "vertical", "theme": "unic", "scenes": [{"type": "title", "l1": "UNIC", "seconds": 3},
                                                                     {"type": "stats", "facts": ["chantiers"], "seconds": 5},
                                                                     {"type": "outro", "brand": True, "seconds": 4}]},
        "seconds": 12, "note": "Scénario écrit par l'IA.", "ai": {"clips": 0, "images": 0},
        "understood": "Une présentation courte de l'entreprise pour WhatsApp.", "assumptions": ["Ton dynamique"], "limits": [],
        "target": 15, "changes": []}


@pytest.fixture(autouse=True)
def _base_prete():
    with TestClient(main.app):   # démarrage de l'appli : tables créées
        yield


def test_le_chat_prepare_le_scenario_et_le_studio_l_ouvre(monkeypatch):
    asked = {}

    def fake_plan(db, brief="", fmt="vertical", theme="auto", current=None, changes=None):
        asked.update(brief=brief, fmt=fmt, theme=theme)
        return FAKE
    monkeypatch.setattr(video_studio, "plan", fake_plan)
    monkeypatch.setattr(settings, "unic_access_code", "")
    with SessionLocal() as db:
        out = AgentSession(db, None, {})("plan_video", {"brief": "Une vidéo de 15 s qui présente UniC pour WhatsApp", "format": "vertical"})
    assert out["ok"] and out["scenes"] == 3 and out["duree_secondes"] == 12 and out["types"] == ["title", "stats", "outro"]
    assert "PAS fabriqué" in out["note"] and "Lancer la fabrication" in out["note"]
    assert asked == {"brief": "Une vidéo de 15 s qui présente UniC pour WhatsApp", "fmt": "vertical", "theme": "auto"}
    with TestClient(main.app) as c:
        d = c.get("/api/website/video/draft").json()
    assert d["brief"].startswith("Une vidéo de 15 s") and d["plan"]["spec"]["scenes"][0]["l1"] == "UNIC" and d["at"]


def test_scenario_impossible_l_ia_le_dit(monkeypatch):
    def broken(*a, **k):
        raise repair.RepairError("Clé Claude absente : je ne peux pas écrire de scénario pour cette demande (ANTHROPIC_API_KEY).", 400)
    monkeypatch.setattr(video_studio, "plan", broken)
    with SessionLocal() as db:
        before = video_studio.draft(db)
        out = AgentSession(db, None, {})("plan_video", {"brief": "Une vidéo sur Dakar"})
        assert "error" in out and "Clé Claude absente" in out["error"]
        assert video_studio.draft(db) == before                                  # rien de rangé à moitié


@pytest.mark.parametrize("reply, succeeded, expected", [
    ("Le scénario est prêt dans le Studio vidéo : relis-le puis lance la fabrication.", ["plan_video"], []),
    ("J'ai préparé le scénario de la vidéo.", ["plan_video"], []),
    ("J'ai préparé le scénario de la vidéo.", [], ["le scénario vidéo"]),
    ("J'ai lancé la vidéo, elle arrive dans tes documents.", ["plan_video"], ["la vidéo"]),
    ("Ta vidéo est prête.", ["plan_video"], ["la vidéo"]),
    ("Veux-tu que je prépare une vidéo pour TikTok ?", [], []),
])
def test_l_ia_ne_peut_pas_dire_que_la_video_est_faite(reply, succeeded, expected):
    assert unbacked(reply, succeeded) == expected
