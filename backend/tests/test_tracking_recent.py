"""Suivi des encaissements : les derniers versements reçus, tous clients confondus (écran d'accueil du suivi)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Quotation, QuotationItem  # noqa: E402


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def _quote(number, who, total):
    db = SessionLocal()
    q = Quotation(number=number, title="Plafond", client_label=who, status="approved", subtotal=total, total=total, currency="FCFA")
    db.add(q)
    db.flush()
    db.add(QuotationItem(quotation_id=q.id, position=1, description="Faux plafond", quantity=1, unit="u", unit_price=total, total=total))
    db.commit()
    qid = q.id
    db.close()
    return qid


def test_recent_receipts_listed_newest_first_with_client_and_limit(c):
    a = _quote("UC-REC-0001-AA", "Awa Recent Un", 1_000_000)
    b = _quote("UC-REC-0002-BB", "Binta Recent Deux", 800_000)
    for qid in (a, b):
        assert c.post(f"/api/tracking/quotes/{qid}/decision", json={"decision": "accepted"}).status_code == 200
    c.post("/api/tracking/receipts", json={"quote_id": a, "amount": 300_000, "kind": "avance", "received_on": "2026-10-10", "method": "Wave"})
    c.post("/api/tracking/receipts", json={"quote_id": b, "amount": 150_000, "kind": "acompte", "received_on": "2026-10-12"})
    from app import tracking
    db = SessionLocal()
    every = tracking._recent_receipts(db, tracking._group(db), limit=500)     # liste complète : d'autres tests ont aussi des versements
    db.close()
    mine = [v for v in every if v["client"].endswith(("Recent Un", "Recent Deux"))]
    assert [v["client"] for v in mine] == ["Binta Recent Deux", "Awa Recent Un"]      # le plus récent d'abord
    assert mine[0]["montant"] == 150_000 and mine[0]["type"] == "acompte" and mine[0]["date"] == "2026-10-12"
    assert mine[1]["moyen"] == "Wave" and mine[1]["devis"] == "UC-REC-0001-AA" and mine[1]["key"]
    for i in range(6):                                                                 # plafonné à 5
        c.post("/api/tracking/receipts", json={"quote_id": a, "amount": 10_000 + i, "kind": "autre", "received_on": "2026-10-13"})
    assert len(c.get("/api/tracking").json()["derniers_versements"]) == 5
