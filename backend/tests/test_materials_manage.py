"""Page Matériaux & prix : ajouter, retirer (sans rien effacer), le chat suit tout de suite ; articles du calcul protégés."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _listed(client, name):
    return [m for m in client.get("/api/materials").json() if m["name"] == name]


def test_add_material_shows_in_list_and_chat_immediately(client):
    r = client.post("/api/materials/quick", json={"name": "Corniche plâtre Test", "unit": "ml", "price": 4500})
    assert r.status_code == 200, r.text
    row = _listed(client, "Corniche plâtre Test")
    assert len(row) == 1 and row[0]["selling_price"] == 4500 and row[0]["unit"] == "ml" and row[0]["removable"] is True
    from app.agent import AgentSession
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        out = AgentSession(db, None, {"owner_message": "prix"})("get_prices", {"query": "corniche plâtre test"})
    finally:
        db.close()
    assert "Corniche plâtre Test" in str(out) and "4500" in str(out)   # le chat connaît le nouveau matériau et son prix


def test_add_without_price_stays_to_enter_never_invented(client):
    r = client.post("/api/materials/quick", json={"name": "Baguette sans prix Test", "unit": "u"})
    assert r.status_code == 200
    assert _listed(client, "Baguette sans prix Test")[0]["selling_price"] is None


def test_duplicate_and_invalid_values_are_refused(client):
    client.post("/api/materials/quick", json={"name": "Doublon Test", "unit": "u", "price": 100})
    dup = client.post("/api/materials/quick", json={"name": "doublon  test", "unit": "u"})
    assert dup.status_code == 400 and "existe déjà" in dup.text
    for bad in (0, -5, 1e12):
        assert client.post("/api/materials/quick", json={"name": "Prix faux Test", "unit": "u", "price": bad}).status_code == 400
    assert client.post("/api/materials/quick", json={"name": "A", "unit": "u"}).status_code == 422
    assert not _listed(client, "Prix faux Test")


def test_remove_hides_from_list_and_chat_but_erases_nothing_and_readd_restores(client):
    from app.database import SessionLocal
    from app.models import Material, MaterialPrice
    mid = client.post("/api/materials/quick", json={"name": "Profil retirable Test", "unit": "barre", "price": 2000}).json()["id"]
    r = client.delete(f"/api/materials/{mid}")
    assert r.status_code == 200 and "devis déjà faits ne changent pas" in r.json()["note"]
    assert not _listed(client, "Profil retirable Test")
    db = SessionLocal()
    try:
        m = db.get(Material, mid)
        assert m is not None and m.is_active is False                                           # rien d'effacé
        assert db.query(MaterialPrice).filter(MaterialPrice.material_id == mid).count() == 1    # historique des prix gardé
        from app.agent import AgentSession
        assert "Profil retirable Test" not in str(AgentSession(db, None, {"owner_message": "prix"})("get_prices", {"query": "profil retirable"}))
    finally:
        db.close()
    again = client.post("/api/materials/quick", json={"name": "Profil retirable Test", "unit": "barre", "price": 2100})
    assert again.status_code == 200 and again.json()["id"] == mid and again.json()["restored"] is True
    assert _listed(client, "Profil retirable Test")[0]["selling_price"] == 2100
    assert client.delete(f"/api/materials/{mid}").status_code == 200
    assert client.delete(f"/api/materials/{mid}").status_code == 404   # déjà retiré


def test_calc_engine_materials_cannot_be_removed(client):
    rows = client.get("/api/materials").json()
    locked = [m for m in rows if m["removable"] is False]
    assert locked, "les articles du calcul automatique doivent être signalés"
    target = next((m for m in locked if "BA13" in m["sku"] or "Plaque" in m["name"]), locked[0])
    r = client.delete(f"/api/materials/{target['id']}")
    assert r.status_code == 400 and "calcul automatique" in r.text
    assert any(m["id"] == target["id"] for m in client.get("/api/materials").json())


def test_unknown_material_removal_is_404(client):
    assert client.delete("/api/materials/inexistant-id").status_code == 404
