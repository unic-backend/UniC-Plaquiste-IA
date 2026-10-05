import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ratelimit  # noqa: E402
from app.documents import UploadRejected, validate_upload  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_security_headers(client):
    h = client.get("/api/ping").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"


def test_cors_not_wildcard_when_origins_set(monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, "allowed_origins", "https://a.example, https://b.example")
    assert main._origins() == ["https://a.example", "https://b.example"]
    monkeypatch.setattr(main.settings, "allowed_origins", "")
    monkeypatch.setattr(main.settings, "unic_env", "production")
    assert main._origins() == []


def test_unhandled_error_is_generic_500(client):
    def boom():
        raise RuntimeError("secret-internal-detail")
    app.router.add_api_route("/api/_boom_test", boom, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())   # avant le fourre-tout du frontend
    r = client.get("/api/_boom_test")
    assert r.status_code == 500
    assert r.json() == {"detail": "Erreur interne du serveur."}
    assert "secret-internal-detail" not in r.text


@pytest.mark.parametrize("name,data", [
    ("virus.exe", b"MZ\x90\x00"),
    ("doc.pdf", b"MZ\x90\x00 not a pdf"),
    ("fake.png", b"%PDF-1.4"),
    ("notes.txt", b"abc\x00def"),
    ("noext", b"hello"),
    ("empty.pdf", b""),
    ("script.sh", b"#!/bin/sh"),
])
def test_malicious_uploads_rejected(name, data):
    with pytest.raises(UploadRejected):
        validate_upload(data, name)


@pytest.mark.parametrize("name,data", [
    ("a.pdf", b"%PDF-1.7 ..."), ("a.PNG", b"\x89PNG\r\n\x1a\nxx"), ("a.txt", b"bonjour"),
    ("a.xlsx", b"PK\x03\x04zz"), ("a.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "),
])
def test_valid_uploads_accepted(name, data):
    assert validate_upload(data, name).startswith(".")


def test_upload_endpoint_rejects_executable(client):
    r = client.post("/api/files", files={"file": ("x.pdf", b"MZ\x90\x00", "application/pdf")})
    assert r.status_code == 415


def test_ratelimit_memory_fallback(monkeypatch):
    monkeypatch.setattr(ratelimit, "_redis_tried", True)
    monkeypatch.setattr(ratelimit, "_redis", None)
    for _ in range(3):
        ratelimit.fail("1.2.3.4", 60)
    assert ratelimit.blocked("1.2.3.4", 3, 60)
    ratelimit.reset("1.2.3.4")
    assert not ratelimit.blocked("1.2.3.4", 3, 60)


def test_logout_revokes_token():
    from app import auth
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        tok = auth.login.__wrapped__ if hasattr(auth.login, "__wrapped__") else None
        assert tok is None  # login exige un compte configuré ; la révocation est testée via logout()
        from app.models import AuthSession
        import hashlib
        from datetime import datetime, timedelta, timezone
        t = "uat_testtoken"
        now = datetime.now(timezone.utc)
        db.add(AuthSession(token_hash=hashlib.sha256(t.encode()).hexdigest(), device="t", created_at=now,
                           last_used=now, expires_at=now + timedelta(days=1)))
        db.commit()
        assert auth.token_valid(db, t)
        auth.logout(db, t)
        db.commit()
        assert not auth.token_valid(db, t)
    finally:
        db.close()
