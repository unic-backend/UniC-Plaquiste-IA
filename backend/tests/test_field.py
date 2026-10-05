import base64
import os
import uuid
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def project_id(client):
    r = client.post("/api/projects", json={"name": "Villa Test Pointage"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _post(client, **kw):
    body = {"client_id": "cid-00000001", "kind": "in"}
    body.update(kw)
    return client.post("/api/checkins", json=body)


def test_checkin_is_idempotent(client, project_id):
    a = _post(client, client_id="dup-test-0001", project_id=project_id, lat=14.7, lon=-17.4)
    b = _post(client, client_id="dup-test-0001", project_id=project_id)
    assert a.status_code == 200 and b.json().get("duplicate") is True and b.json()["id"] == a.json()["id"]


@pytest.mark.parametrize("kw,code", [
    ({"lat": 200, "lon": 0}, 422), ({"lat": 10}, 400), ({"kind": "pause"}, 422),
    ({"project_id": "nope"}, 404), ({"at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}, 400),
])
def test_checkin_rejects_impossible_data(client, kw, code):
    assert _post(client, client_id=f"bad-{abs(hash(str(kw)))}", **kw).status_code == code


def test_hours_pair_in_and_out_and_open_shift_not_counted(client):
    p = client.post("/api/projects", json={"name": "Chantier Heures"}).json()["id"]
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    for i, (k, dt) in enumerate([("in", 0), ("out", 4), ("in", 5)]):   # 4 h travaillées puis une arrivée sans départ
        assert _post(client, client_id=f"hrs-test-{i}-{p[:6]}", kind=k, project_id=p, at=(t0 + timedelta(hours=dt)).isoformat()).status_code == 200
    s = client.get(f"/api/checkins/summary?project_id={p}").json()
    assert s["chantiers"][0]["heures"] == 4.0
    assert len(s["en_cours"]) == 1


def _quote_id(client):
    from app.database import SessionLocal
    from app.models import Quotation, QuotationItem
    db = SessionLocal()
    try:
        q = Quotation(number="SIG-" + uuid.uuid4().hex[:8], client_label="Diallo", subtotal=500.0, total=500.0, currency="FCFA")
        q.items = [QuotationItem(position=1, description="Cloison", quantity=10, unit="m2", unit_price=50.0, total=500.0)]
        db.add(q)
        db.commit()
        return q.id
    finally:
        db.close()


def test_signature_requires_consent_and_valid_png(client):
    qid = _quote_id(client)
    ok = {"name": "M. Diallo", "image": DATA_URL, "consent": True}
    assert client.post(f"/api/quotes/{qid}/signature", json={**ok, "consent": False}).status_code == 400
    assert client.post(f"/api/quotes/{qid}/signature", json={**ok, "image": "data:image/png;base64," + base64.b64encode(b"<html>" + b"x" * 30).decode()}).status_code == 400
    assert client.post(f"/api/quotes/{qid}/signature", json={**ok, "image": "data:text/html;base64,AAAAAAAAAAAAAAAAAAAAAA=="}).status_code == 400
    assert client.post("/api/quotes/inconnu/signature", json=ok).status_code == 404


def test_signature_detects_quote_changed_after_signing(client):
    qid = _quote_id(client)
    r = client.post(f"/api/quotes/{qid}/signature", json={"name": "M. Diallo", "image": DATA_URL, "consent": True})
    assert r.status_code == 200 and r.json()["unchanged_since_signature"] is True
    sid = r.json()["id"]
    assert client.get(f"/api/signatures/{sid}.png").content == PNG
    from app.database import SessionLocal
    from app.models import Quotation
    db = SessionLocal()
    try:
        db.get(Quotation, qid).total = 999.0
        db.commit()
    finally:
        db.close()
    assert client.get(f"/api/quotes/{qid}/signature").json()[0]["unchanged_since_signature"] is False
