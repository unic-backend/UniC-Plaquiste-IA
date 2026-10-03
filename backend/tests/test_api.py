import io
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Isolate test data
os.environ.setdefault("UNIC_DATA_DIR", str(Path("/tmp/unic-test-data")))
os.environ.setdefault("UNIC_SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("UNIC_ADMIN_EMAIL", "marco.r@example.org")
os.environ.setdefault("UNIC_ADMIN_PASSWORD", "UniC-Plaquiste-2026")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token():
    return None


def auth(token):
    return {}


def test_no_login_needed(client):
    assert client.get("/api/auth/me").status_code == 200


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["database"]["status"] == "ok"
    caps = {c["id"]: c for c in data["capabilities"]}
    assert caps["create_quote"]["available"] is True
    assert caps["ocr_document"]["available"] is False
    assert caps["publish_social_post"]["available"] is False


def test_materials_have_no_invented_prices(client, token):
    r = client.get("/api/materials", headers=auth(token))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 5
    for m in rows:
        assert m["selling_price"] is None
        assert m["purchase_price"] is None


def test_chat_partition_and_quote_pdf(client, token):
    h = auth(token)
    r = client.post("/api/chat", json={"message": "cloison 10 m x 2,5 m deux faces"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    cid = data["conversation_id"]
    content = data["message"]["content"]
    assert "Surface brute" in content
    assert "50" in content  # 10*2.5*2 = 50 m²
    assert "prix" in content.lower() or "manqu" in content.lower()

    r2 = client.post("/api/chat", json={"conversation_id": cid, "message": "fais le devis"}, headers=h)
    assert r2.status_code == 200, r2.text
    meta = r2.json()["message"]["meta"]
    assert meta["artifacts"], "Un PDF réel doit être produit"
    art = meta["artifacts"][0]
    assert art["status"] == "ready"
    assert art["filename"].endswith(".pdf")
    dl = client.get(art["download_url"], headers=h)
    assert dl.status_code == 200
    assert dl.content[:4] == b"%PDF"
    assert len(dl.content) > 500


def test_customer_crud(client, token):
    h = auth(token)
    r = client.post("/api/customers", json={"name": "FAST GROUP"}, headers=h)
    assert r.status_code == 200
    cid = r.json()["id"]
    r2 = client.get("/api/customers", headers=h)
    names = [c["name"] for c in r2.json()]
    assert "FAST GROUP" in names
    r3 = client.put(f"/api/customers/{cid}", json={"name": "FAST GROUP", "city": "Diamniadio"}, headers=h)
    assert r3.json()["city"] == "Diamniadio"


def test_upload_txt_and_search(client, token):
    h = auth(token)
    content = b"Plan RDC\nCloison BA13 12 m\nPorte 0.90 x 2.04\n"
    r = client.post(
        "/api/files",
        headers=h,
        files={"file": ("plan.txt", io.BytesIO(content), "text/plain")},
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    r2 = client.get(f"/api/files/{fid}/search", params={"q": "porte"}, headers=h)
    assert r2.status_code == 200
    assert r2.json()["hits"]


def test_price_not_invented_in_quote_when_missing(client, token):
    h = auth(token)
    client.post("/api/chat", json={"message": "cloison 3x2.5 une face"}, headers=h)
    # new conversation quote
    r = client.post("/api/conversations", headers=h)
    cid = r.json()["id"]
    client.post("/api/chat", json={"conversation_id": cid, "message": "cloison 3 m x 2,5 m une face"}, headers=h)
    r2 = client.post("/api/chat", json={"conversation_id": cid, "message": "creer un devis"}, headers=h)
    quotes = client.get("/api/quotes", headers=h).json()
    assert quotes
    q = quotes[0]
    assert q["prices_complete"] is False
    assert q["total"] is None
    for it in q["items"]:
        assert it["unit_price"] is None


def test_quote_in_one_message(client):
    r = client.post("/api/chat", json={"message": "Cloison 320 m × 2,50 m, deux faces. Fais le devis."})
    assert r.status_code == 200
    assert "DEV-" in r.json()["message"]["content"]


def test_greeting_and_price_question(client):
    assert "UniC AI" in client.post("/api/chat", json={"message": "bonjour"}).json()["message"]["content"]
    r = client.post("/api/chat", json={"message": "quel est le prix du BA13 ?"}).json()
    assert "BA13" in r["message"]["content"]


def test_dimension_with_sur(client):
    r = client.post("/api/chat", json={"message": "combien de plaques pour un mur de 12m sur 2.6"}).json()
    assert "12" in r["message"]["content"] and "2.6" in r["message"]["content"]
