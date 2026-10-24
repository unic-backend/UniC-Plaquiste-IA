"""L'IA se souvient de TOUTES les conversations : une vieille conversation (même archivée, même enfouie sous des centaines
de messages plus récents) est retrouvée, avec sa date et ses passages exacts ; rien trouvé = elle le dit."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import memory as mem
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Conversation, Message


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def _conv(c, title: str, msgs: list[tuple[str, str]], days_ago: float, archived: bool = False) -> str:
    cid = c.post("/api/conversations", json={}).json()["id"]
    at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with SessionLocal() as db:
        conv = db.get(Conversation, cid)
        conv.title, conv.archived = title, archived
        for i, (role, text) in enumerate(msgs):
            db.add(Message(conversation_id=cid, role=role, content=text, created_at=at + timedelta(minutes=i)))
        db.commit()
    return cid


def test_une_vieille_conversation_archivee_est_retrouvee_sous_des_centaines_de_messages(c):
    old = _conv(c, "Plafond Tivaouane", [
        ("user", "Pour Mbacké Sarr à Tivaouane on part sur un plafond staff de 38 m², 9 500 FCFA le m²."),
        ("assistant", "Noté : plafond staff 38 m² à 9 500 FCFA le m² pour Mbacké Sarr, Tivaouane."),
        ("user", "Et il veut une corniche en plus dans le salon."),
    ], days_ago=200, archived=True)
    _conv(c, "Bavardages", [("user" if i % 2 == 0 else "assistant", f"Message ordinaire numéro {i} sur un plafond à Dakar.")
                            for i in range(850)], days_ago=1)

    with SessionLocal() as db:   # le rappel automatique ne s'arrête plus aux 800 derniers messages
        assert "38 m²" in mem.recall_past(db, "Le plafond de Mbacké Sarr à Tivaouane, c'était combien le m² ?")
        out = AgentSession(db, None, {})("search_conversations",
                                         {"query": "retrouve la conversation où on a parlé du plafond de Tivaouane"})
    hit = next(x for x in out["conversations"] if x["id"] == old)
    assert hit["titre"] == "Plafond Tivaouane" and hit["archivee"] is True
    textes = [e["texte"] for e in hit["extraits"]]
    assert any("9 500 FCFA" in t for t in textes)
    dates = [datetime.strptime(e["date"], "%d/%m/%Y") for e in hit["extraits"]]
    assert dates == sorted(dates) and hit["date"] == hit["extraits"][-1]["date"]       # du plus ancien au plus récent
    assert out["conversations"][0]["id"] == old                                        # la bonne en premier, pas les bavardages


def test_une_periode_seule_et_des_dates_precises(c):
    cid = _conv(c, "Rails Sotiba", [("user", "Commande 40 rails de 3 m chez Sotiba pour le chantier de Ngor.")], days_ago=8)
    with SessionLocal() as db:
        s = AgentSession(db, None, {})
        assert any(x["id"] == cid for x in s("search_conversations", {"query": "qu'est-ce qu'on a dit la semaine dernière"})["conversations"])
        day = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")
        found = s("search_conversations", {"query": "rails Sotiba", "date_from": day, "date_to": day})["conversations"]
        assert [x["id"] for x in found] == [cid]
        assert s("search_conversations", {"query": "rails Sotiba", "date_to": "2001-01-01"})["conversations"] == []   # hors période
        assert "illisible" in s("search_conversations", {"query": "rails", "date_from": "hier"})["error"]


def test_rien_trouve_l_ia_doit_le_dire(c):
    with SessionLocal() as db:
        out = AgentSession(db, None, {})("search_conversations", {"query": "hélicoptère Kédougou"})
    assert out["conversations"] == [] and "n'invente pas" in out["note"]


def test_la_recherche_de_la_barre_laterale_lit_aussi_les_messages(c):
    cid = _conv(c, "Nouvelle conversation", [("user", "Le portail de Mme Thiaw à Yoff fait 4 mètres de large.")], days_ago=3)
    assert cid in [x["id"] for x in c.get("/api/conversations", params={"q": "Thiaw"}).json()]
    assert cid in [x["id"] for x in c.get("/api/conversations", params={"q": "Nouvelle conv"}).json()]   # le titre compte toujours
    assert cid not in [x["id"] for x in c.get("/api/conversations", params={"q": "Kédougou"}).json()]
