"""Détection des secrets illisibles : exacte (casse comprise) et sans faux positif."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import secret_health  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_a_lowercase_look_alike_value_is_not_reported_as_an_unreadable_secret(client):
    from app.database import SessionLocal
    from app.models import AppSetting
    db = SessionLocal()
    db.add(AppSetting(key="note_test_casse", value="gaaaaa une simple note, pas un secret"))
    db.commit()
    try:
        assert "note_test_casse" not in {x["key"] for x in secret_health.unreadable(db)}
    finally:
        db.delete(db.get(AppSetting, "note_test_casse"))
        db.commit()
        db.close()
