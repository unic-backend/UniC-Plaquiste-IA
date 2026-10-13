"""Réglages : une valeur « null » sur un champ obligatoire ne casse rien."""
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
    with TestClient(app) as c:
        yield c


def test_settings_null_on_a_required_field_keeps_the_value_instead_of_a_500(client):
    before = client.get("/api/settings").json()
    r = client.put("/api/settings", json={"name": None, "quote_validity_days": None, "default_waste": None, "board_width_m": None})
    assert r.status_code == 200
    after = r.json()
    for k in ("name", "quote_validity_days", "default_waste", "board_width_m"):
        assert after[k] == before[k], k                                                       # rien n'est effacé ni cassé
    r2 = client.put("/api/settings", json={"vat_rate": None})                                  # champ facultatif : « sans valeur » reste possible
    assert r2.status_code == 200 and r2.json()["vat_rate"] is None
