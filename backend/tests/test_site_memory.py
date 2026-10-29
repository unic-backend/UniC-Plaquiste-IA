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


# ---------- une ancienne information, une hypothèse ou un document ne remplace jamais une valeur confirmée ----------

def test_unrelated_price_lines_are_not_reported_as_conflicts(db):
    memory.add(db, "Une barre de fourrure coûte 1 200 FCFA (prix d'une barre, pas d'un paquet).", source="user", pinned=True)
    memory.add(db, "Une barre (fourrure, montant, rail) mesure 2,80 m.", source="user", pinned=True)
    memory.add(db, "Pivot = 6 500 FCFA le paquet de 100 ; chevilles à laiton = 6 000 FCFA le paquet de 100.", source="user", pinned=True)
    db.commit()
    mine = [c for c in memory.conflicts(db) if any(w in c["a"]["text"] + c["b"]["text"] for w in ("barre", "Pivot"))]
    assert mine == []   # avant : « fcfa », « prix », « paquet » suffisaient à crier au conflit


def test_imported_old_value_never_replaces_a_confirmed_one_and_is_flagged(db):
    memory.add(db, "La plaque BA13 coûte 5500 FCFA chez le fournisseur Sodimat", source="user", pinned=True)
    old = memory.add(db, "La plaque BA13 coûte 4500 FCFA chez le fournisseur Sodimat", source="import")   # ancien export
    db.commit()
    assert old is not None and old.nature == "inference"                      # jamais « valable maintenant »
    active = [m.text for m in db.query(memory.Memory).filter(memory.Memory.state == "active")]
    assert any("5500" in t for t in active)                                   # la valeur confirmée est toujours là
    cs = [c for c in memory.conflicts(db) if "Sodimat" in c["a"]["text"]]
    assert len(cs) == 1
    text = memory.block(db, "prix plaque BA13 Sodimat")
    assert "supposition non confirmée" in text and "confirmée par le patron" in text and "ne remplace JAMAIS" in text


def test_two_confirmed_values_are_both_kept_and_the_order_is_shown(db):
    first = memory.add(db, "Le sac de ciment colle coûte 5000 FCFA chez le fournisseur Cimenco", source="user", pinned=True)
    db.commit()
    second = memory.add(db, "Le sac de ciment colle coûte 5500 FCFA chez le fournisseur Cimenco", source="user", pinned=True)
    db.commit()
    assert first is not None and second is not None and first.id != second.id   # rien n'est écrasé en silence
    c = [x for x in memory.conflicts(db) if "Cimenco" in x["a"]["text"]][0]
    assert c["plus_recent"] in (first.id, second.id)
    assert "plus récente" in memory.block(db, "prix sac ciment colle Cimenco")


def test_conflicts_limited_to_shown_memories_equal_the_full_scan_restricted_and_prompt_is_unchanged(db):
    ids = []
    for txt in ("La plaque hydrofuge Zorba coûte 7 100 FCFA chez Alpha", "La plaque hydrofuge Zorba coûte 8 300 FCFA chez Alpha",
                "Le rail Zorba mesure 3 m chez Beta pour 2 500 FCFA", "Le rail Zorba mesure 3 m chez Beta pour 2 900 FCFA"):
        m = memory.add(db, txt, source="user")
        ids.append(m.id if hasattr(m, "id") else None)
    db.commit()
    full = memory.conflicts(db)
    assert full, "le jeu d'essai doit contenir des divergences"
    some = {c["a"]["id"] for c in full[:1]}
    part = memory.conflicts(db, only=some)
    expected = [c for c in full if c["a"]["id"] in some or c["b"]["id"] in some]
    assert [(c["a"]["id"], c["b"]["id"]) for c in part] == [(c["a"]["id"], c["b"]["id"]) for c in expected]   # même résultat, même ordre
    assert memory.conflicts(db, only=set()) == []
    real = memory.conflicts

    def old_style(db_, only=None):   # ancien comportement : balayage complet à chaque message
        return real(db_)
    for query in ("plaque hydrofuge Zorba", "rail Zorba Beta", "bonjour"):
        fast = memory.block(db, query)
        memory.conflicts = old_style
        try:
            slow = memory.block(db, query)
        finally:
            memory.conflicts = real
        assert fast == slow, query                                                                              # le texte envoyé à l'IA ne change pas
