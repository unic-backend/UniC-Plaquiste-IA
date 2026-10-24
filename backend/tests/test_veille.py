"""Veille du matin : coupée par défaut, activée ou coupée par le patron ; chaque jour, l'actualité de ses sujets est rangée,
datée et sourcée, dans la bibliothèque. Rien de nouveau ou sans source : rien n'est rangé. Après 30 jours : retirée, jamais effacée."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import context, library, veille
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import StoredFile

NEWS = ("- 22/10/2026 : le sac de ciment Sococim passe à 4 350 FCFA à Dakar [1].\n"
        "- 23/10/2026 : nouvelle cimenterie annoncée à Pout [2].")


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    monkeypatch.setattr(settings, "web_search_enabled", True)
    with TestClient(app) as client:
        _reset()
        yield client
        _reset()   # jamais de veille laissée active pour les tests suivants (alerts.tick la lancerait)


def _reset() -> None:   # chaque test repart d'une veille vierge
    with SessionLocal() as db:
        veille._put(db, {})
        db.commit()


@pytest.fixture
def claude(monkeypatch):
    asked: list[dict] = []
    replies = {"ciment": (NEWS, [{"title": "APS", "url": "https://aps.sn/ciment"}, {"title": "Le Soleil", "url": "https://lesoleil.sn/pout"}]),
               "kédougou": ("RIEN DE NOUVEAU", []),
               "sans source": ("- Une rumeur sans date.", [])}

    def complete(self, messages, **kw):
        asked.append({**kw, "system": messages[0]["content"], "user": messages[1]["content"]})
        topic = messages[1]["content"].lower()
        text, sources = next((v for k, v in replies.items() if k in topic), ("RIEN DE NOUVEAU", []))
        return AIResult(text, "claude", "claude-sonnet-5-5", True, "", raw={"usage": [], "sources": sources})
    # sur la classe (pas sur l'objet partagé) : remis exactement en place après le test
    monkeypatch.setattr(type(PROVIDERS["claude"]), "health", lambda self: {"available": True})
    monkeypatch.setattr(type(PROVIDERS["claude"]), "complete", complete)
    return asked


def test_coupee_par_defaut_puis_activee_et_coupee(c):
    v = c.get("/api/veille").json()
    assert v["on"] is False and v["topics"] == [] and v["running"] is False
    with SessionLocal() as db:
        assert not veille.due(db)
    assert c.post("/api/veille", json={"on": True, "topics": []}).status_code == 400              # rien à surveiller
    assert c.post("/api/veille", json={"on": True, "topics": [f"sujet {i}" for i in range(6)]}).status_code == 400
    v = c.post("/api/veille", json={"on": True, "topics": ["Prix du ciment", " prix  du ciment ", "BTP Dakar"], "hour": 6}).json()
    assert v["on"] and v["topics"] == ["Prix du ciment", "BTP Dakar"] and v["hour"] == 6          # doublon retiré
    with SessionLocal() as db:
        morning = datetime.now(timezone.utc).replace(hour=8)
        assert veille.due(db, morning) and not veille.due(db, morning.replace(hour=5))           # pas avant l'heure choisie
    v = c.post("/api/veille", json={"on": False, "topics": ["Prix du ciment"]}).json()
    assert v["on"] is False and v["topics"] == ["Prix du ciment"]                                 # coupée : sujets gardés
    with SessionLocal() as db:
        assert not veille.due(db, datetime.now(timezone.utc).replace(hour=8))


def test_la_veille_range_les_nouvelles_sourcees_et_l_ia_les_retrouve(c, claude):
    c.post("/api/veille", json={"on": True, "topics": ["Prix du ciment au Sénégal", "Mines d'or de Kédougou", "Bruit sans source"]})
    now = datetime.now(timezone.utc).replace(hour=9)
    with SessionLocal() as db:
        out = veille.run(db, now=now)
        assert [r["etat"] for r in out] == ["ok", "rien", "rien"]                                 # rien de nouveau, ou sans source : rien rangé
        assert out[0]["nb_sources"] == 2 and "4 350 FCFA" in out[0]["apercu"]
        assert not veille.due(db, now)                                                            # faite aujourd'hui
        assert veille.due(db, now + timedelta(days=1))                                            # demain : à refaire
        _kb, docs, _ = context.knowledge_and_documents(db, "Combien coûte le sac de ciment Sococim à Dakar ?")
        assert "4 350 FCFA" in docs and "Bibliothèque · Savoir - Veille" in docs
    assert claude[0]["web"] is True and claude[0]["web_max_uses"] == veille.SEARCHES_PER_TOPIC and "DONNÉES" in claude[0]["system"]
    assert len(claude) == 3                                                                       # une recherche courte par sujet
    v = c.get("/api/veille").json()
    assert v["last_day"] == now.date().isoformat() and len(v["last"]) == 3


def test_claude_indisponible_note_l_echec_sans_reessayer_en_boucle(c, monkeypatch):
    monkeypatch.setattr(type(PROVIDERS["claude"]), "health", lambda self: {"available": False})
    c.post("/api/veille", json={"on": True, "topics": ["Prix du ciment"]})
    assert c.post("/api/veille/run").status_code == 400
    now = datetime.now(timezone.utc).replace(hour=9)
    with SessionLocal() as db:
        out = veille.run(db, now=now)
        assert out[0]["etat"] == "erreur" and "Claude" in out[0]["detail"]
        assert not veille.due(db, now)


def test_une_vieille_veille_est_retiree_jamais_effacee(c, claude):
    c.post("/api/veille", json={"on": True, "topics": ["Prix du ciment"]})
    with SessionLocal() as db:
        old = veille.run(db, now=datetime.now(timezone.utc) - timedelta(days=40))[0]["file_id"]
        assert db.get(StoredFile, old).kind == library.KIND
        veille.run(db, now=datetime.now(timezone.utc))
        db.expire_all()
        assert db.get(StoredFile, old).kind == library.RETIRED                                    # gardée, plus consultée


def test_lancer_maintenant_une_fois_toutes_les_dix_minutes(c, claude, monkeypatch):
    assert c.post("/api/veille/run").status_code == 400                                           # aucun sujet
    c.post("/api/veille", json={"on": False, "topics": ["Prix du ciment"]})
    started = []
    monkeypatch.setattr(veille.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: started.append(target)})())
    assert c.post("/api/veille/run").json() == {"started": True}
    assert c.post("/api/veille/run").status_code == 409                                           # déjà en cours
    started[0]()                                                                                  # la veille tourne et se termine
    assert c.post("/api/veille/run").status_code == 409                                           # moins de 10 minutes après
    assert c.get("/api/veille").json()["last"][0]["etat"] == "ok"
