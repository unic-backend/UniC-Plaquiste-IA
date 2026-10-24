"""Bibliothèque de sources : le patron donne ses livres, PDF et liens ; l'IA les consulte EN PREMIER ; une source retirée
reste gardée mais n'est plus consultée."""
import pytest
from fastapi.testclient import TestClient

from app import context
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import StoredFile


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    monkeypatch.setattr(settings, "web_search_enabled", True)
    with TestClient(app) as client:
        yield client


GUIDE = ("Guide de l'isolation acoustique. Une cloison Placostil 72/48 avec laine minérale de 45 mm atteint un affaiblissement "
         "acoustique Rw de 41 dB. Doubler la plaque de chaque côté gagne environ 6 dB.")


def test_ma_source_est_consultee_en_premier_puis_retiree_et_remise(c):
    r = c.post("/api/library/files", files={"file": ("guide-acoustique.txt", GUIDE.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    c.post("/api/files", files={"file": ("note-chantier.txt", "Affaiblissement acoustique Rw de la cloison du salon à revoir.".encode(), "text/plain")})
    src = next(s for s in c.get("/api/library").json()["sources"] if s["id"] == fid)
    assert src["active"] and src["passages"] >= 1 and not src["appris_par_ia"]
    question = "Quel affaiblissement acoustique Rw pour une cloison Placostil 72/48 avec laine minérale ?"
    with SessionLocal() as db:
        _kb, docs, _ = context.knowledge_and_documents(db, question)
    assert docs.index("Bibliothèque · guide-acoustique.txt") < docs.index("note-chantier.txt")    # sa source d'abord
    assert "41 dB" in docs

    assert c.post(f"/api/library/{fid}/active", json={"on": False}).json() == {"id": fid, "active": False}
    with SessionLocal() as db:
        assert "41 dB" not in context.knowledge_and_documents(db, question)[1]                     # retirée : plus consultée
        assert db.get(StoredFile, fid) is not None                                                  # mais jamais effacée
    assert not next(s for s in c.get("/api/library").json()["sources"] if s["id"] == fid)["active"]
    c.post(f"/api/library/{fid}/active", json={"on": True})
    with SessionLocal() as db:
        assert "41 dB" in context.knowledge_and_documents(db, question)[1]
    assert c.post("/api/library/inconnu/active", json={"on": True}).status_code == 400


def test_apprendre_un_lien_depuis_la_bibliotheque(c, monkeypatch):
    claude = PROVIDERS["claude"]
    monkeypatch.setattr(type(claude), "health", lambda self: {"available": True})
    monkeypatch.setattr(type(claude), "complete", lambda self, messages, **kw: AIResult(
        "# Le bouye\n\nLe bouye est une boisson à base de pain de singe, le fruit du baobab.", "claude", "claude-sonnet-5-5", True, "",
        raw={"usage": [], "sources": []}))
    r = c.post("/api/library/url", json={"url": "https://exemple.sn/bouye"})
    assert r.status_code == 200 and r.json()["titre"] == "Le bouye"
    assert any(s["nom"].startswith("Savoir - ") and s["appris_par_ia"] for s in c.get("/api/library").json()["sources"])
    assert c.post("/api/library/url", json={"url": "ftp://exemple.sn/x"}).status_code == 400
