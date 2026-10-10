"""Mémoire par client/chantier : rien ne se mélange d'un client à l'autre, les secrets restent refusés."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agents, memory  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def db(client):
    from app.database import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


def _quote(db, name, lieu):
    from app import services as svc
    from app.models import Quotation, QuotationItem
    q = Quotation(number=svc.document_number(db, name, lieu=lieu), client_label=name, site_location=lieu, status="draft", currency="FCFA", subtotal=1000.0, total=1000.0)
    q.items = [QuotationItem(position=1, description="Cloison", quantity=10, unit="m2", unit_price=100.0, total=1000.0)]
    db.add(q)
    db.commit()
    return q


def _session(db, owner="retiens pour ce client"):
    from app.agent import AgentSession
    return AgentSession(db, None, {"owner_message": owner})


def test_same_sentence_for_two_clients_is_two_memories_not_a_duplicate(db):
    _quote(db, "Sarr Memoire Alpha", "Mermoz")
    _quote(db, "Ndiaye Memoire Beta", "Almadies")
    s = _session(db)
    a = s("remember", {"text": "Le gardien ouvre le portail seulement après 8 heures", "client": "Sarr Memoire"})
    b = s("remember", {"text": "Le gardien ouvre le portail seulement après 8 heures", "client": "Ndiaye Memoire"})
    assert a["ok"] and b["ok"] and a["id"] != b["id"], (a, b)
    assert "Sarr" in a["portee"] and "Ndiaye" in b["portee"]


def test_site_memory_returns_only_that_client_and_general_block_stays_clean(db):
    _quote(db, "Fall Memoire Gamma", "Ouakam")
    _quote(db, "Ba Memoire Delta", "Yoff")
    s = _session(db)
    s("remember", {"text": "Peinture satinée blanc cassé exigée salon Gamma", "client": "Fall Memoire"})
    s("remember", {"text": "Accès par l'escalier de service Delta uniquement", "client": "Ba Memoire"})
    fall = s("site_memory", {"client": "Fall Memoire"})
    texts = " ".join(x["texte"] for x in fall["souvenirs"])
    assert "Gamma" in texts and "Delta" not in texts
    assert fall["client"].startswith("Fall") and fall["nb_devis"] == 1
    general = memory.block(db, "peinture escalier salon accès")
    assert "Gamma" not in general and "Delta" not in general   # jamais dans la mémoire générale


def test_client_ambiguous_or_unknown_is_asked_never_guessed(db):
    _quote(db, "Diop Memoire Un", "Pikine")
    _quote(db, "Diop Memoire Deux", "Rufisque")
    s = _session(db)
    amb = s("remember", {"text": "Clés chez la voisine du deuxième", "client": "Diop Memoire"})
    assert "error" in amb and "Plusieurs" in str(amb)
    unk = s("site_memory", {"client": "Personne Inconnue Zzz"})
    assert "error" in unk
    from app.models import Memory
    assert not db.query(Memory).filter(Memory.text.ilike("%voisine du deuxième%")).first()


def test_secret_is_still_refused_for_a_client(db):
    _quote(db, "Camara Memoire Eps", "Thiès")
    out = _session(db)("remember", {"text": "Mot de passe wifi : sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789", "client": "Camara Memoire"})
    assert "error" in out


def test_numbers_of_two_clients_are_not_reported_as_a_conflict(db):
    _quote(db, "Sy Memoire Zeta", "Medina")
    _quote(db, "Kane Memoire Eta", "Fann")
    s = _session(db)
    s("remember", {"text": "Hauteur sous plafond chambre 2,70 m", "client": "Sy Memoire"})
    s("remember", {"text": "Hauteur sous plafond chambre 3,10 m", "client": "Kane Memoire"})
    both = [c for c in memory.conflicts(db) if "chambre" in c["a"]["text"] and ("2,70" in c["a"]["text"] + c["b"]["text"])]
    assert not both


def test_same_client_contradiction_is_still_reported(db):
    _quote(db, "Thiam Memoire Theta", "Sacre-Coeur")
    s = _session(db)
    s("remember", {"text": "Hauteur sous plafond chambre 2,70 m", "client": "Thiam Memoire"})
    s("remember", {"text": "Hauteur sous plafond chambre 3,10 m", "client": "Thiam Memoire"})
    assert any("chambre" in c["a"]["text"] for c in memory.conflicts(db))


def test_site_memory_is_read_only_so_safe_for_automatic_agents():
    assert "site_memory" in agents.SAFE_TOOLS


def test_general_rule_without_client_is_unchanged(db):
    out = _session(db, "retiens pour toujours")("remember", {"text": "Toujours arrondir les plaques au supérieur sur mes devis"})
    assert out["ok"] and out["portee"] == "règle générale"
    assert "arrondir les plaques" in memory.block(db, "arrondir plaques devis")
