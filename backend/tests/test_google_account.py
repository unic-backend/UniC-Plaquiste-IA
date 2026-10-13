"""Connexion de la fiche Google depuis l'appli : identifiants testés avant d'être gardés, chiffrés, jamais renvoyés."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import google_account, google_business as gb, secrets_box  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting  # noqa: E402

CID = "874006341150-abcdefghijklmnop.apps.googleusercontent.com"
SECRET = "GOCSPX-secret-value-123"
TOKEN = "1//refresh-token-value-0123456789"


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data or {}

    def json(self):
        return self._data


class FakeHttp:
    """Faux Google : `plan` donne la réponse de chaque point d'accès."""
    plan: dict = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None, **k):
        return self.plan["token"]

    def get(self, url, headers=None, params=None, **k):
        if url.endswith("/accounts"):
            return self.plan["accounts"]
        by_account = self.plan.get("by_account")
        if by_account is not None:
            return by_account[url.split("/accounts/")[1].split("/")[0]]
        return self.plan["locations"]


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeHttp.plan = {
        "token": Resp(200, {"access_token": "at", "expires_in": 3000}),
        "accounts": Resp(200, {"accounts": [{"name": "accounts/111"}]}),
        "locations": Resp(200, {"locations": [{"name": "locations/222", "title": "UniC Plaquiste"}]}),
    }
    monkeypatch.setattr(google_account.httpx, "Client", FakeHttp)
    for k in ("google_client_id", "google_client_secret", "google_refresh_token", "gbp_account_id", "gbp_location_id"):
        monkeypatch.setattr(gb.settings, k, "", raising=False)
    gb.set_runtime(None)
    yield
    db = SessionLocal()
    try:
        google_account.disconnect(db)
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def booted():
    with TestClient(app):
        yield


def _db():
    return SessionLocal()


def test_connect_discovers_account_and_location_and_encrypts():
    db = _db()
    try:
        out = google_account.connect(db, CID, SECRET, TOKEN)
        assert out == {"connected": True, "title": "UniC Plaquiste", "unreadable": False}
        assert gb.configured() and gb._v("gbp_account_id") == "111" and gb._v("gbp_location_id") == "222"
        for key, plain in (("gbp_client_id", CID), ("gbp_client_secret", SECRET), ("gbp_refresh_token", TOKEN)):
            stored = db.get(AppSetting, key).value
            assert plain not in stored and stored.startswith("gAAAAA") and secrets_box.decrypt(stored) == plain
    finally:
        db.close()


def test_rejected_credentials_store_nothing():
    FakeHttp.plan["token"] = Resp(400, {"error": "invalid_grant"})
    db = _db()
    try:
        with pytest.raises(google_account.GoogleAccountError) as e:
            google_account.connect(db, CID, SECRET, TOKEN)
        assert "refuse" in str(e.value) and SECRET not in str(e.value) and TOKEN not in str(e.value)
        assert db.get(AppSetting, "gbp_refresh_token") is None and not gb.configured()
    finally:
        db.close()


def test_api_not_enabled_gives_an_actionable_message():
    FakeHttp.plan["accounts"] = Resp(403)
    db = _db()
    try:
        with pytest.raises(google_account.GoogleAccountError) as e:
            google_account.connect(db, CID, SECRET, TOKEN)
        assert "active les API" in str(e.value)
        assert db.get(AppSetting, "gbp_client_secret") is None
    finally:
        db.close()


def test_no_location_or_no_account_is_reported():
    db = _db()
    try:
        FakeHttp.plan["accounts"] = Resp(200, {"accounts": []})
        with pytest.raises(google_account.GoogleAccountError):
            google_account.connect(db, CID, SECRET, TOKEN)
        FakeHttp.plan["accounts"] = Resp(200, {"accounts": [{"name": "accounts/111"}]})
        FakeHttp.plan["locations"] = Resp(200, {"locations": []})
        with pytest.raises(google_account.GoogleAccountError):
            google_account.connect(db, CID, SECRET, TOKEN)
    finally:
        db.close()


@pytest.mark.parametrize("cid,secret,token", [("pas-un-id", SECRET, TOKEN), (CID, "court", TOKEN), (CID, SECRET, "court"), ("", "", "")])
def test_malformed_input_is_refused_before_calling_google(cid, secret, token, monkeypatch):
    monkeypatch.setattr(google_account.httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Google ne doit pas être appelé")))
    db = _db()
    try:
        with pytest.raises(google_account.GoogleAccountError):
            google_account.connect(db, cid, secret, token)
    finally:
        db.close()


def test_runtime_is_restored_after_restart_and_cleared_on_disconnect():
    db = _db()
    try:
        google_account.connect(db, CID, SECRET, TOKEN)
        gb.set_runtime(None)                       # redémarrage du serveur
        assert not gb.configured()
        google_account.load_into_runtime(db)
        assert gb.configured()
        out = google_account.disconnect(db)
        assert out["connected"] is False and not gb.configured()
        assert db.get(AppSetting, "gbp_account_id") is None
    finally:
        db.close()


def test_unreadable_secret_is_flagged_not_connected(monkeypatch):
    db = _db()
    try:
        google_account.connect(db, CID, SECRET, TOKEN)
        monkeypatch.setattr(secrets_box, "decrypt", lambda t: None)   # clé de chiffrement changée
        out = google_account.status(db)
        assert out["connected"] is False and out["unreadable"] is True
        google_account.load_into_runtime(db)
        assert not gb.configured()
    finally:
        db.close()


def test_environment_variables_win_over_the_app_connection(monkeypatch):
    db = _db()
    try:
        google_account.connect(db, CID, SECRET, TOKEN)
        monkeypatch.setattr(gb.settings, "gbp_location_id", "ENV-LOC", raising=False)
        assert gb._v("gbp_location_id") == "ENV-LOC"
    finally:
        db.close()


def test_endpoints_never_return_secrets():
    with TestClient(app) as c:
        r = c.put("/api/google/account", json={"client_id": CID, "client_secret": SECRET, "refresh_token": TOKEN})
        assert r.status_code == 200
        for resp in (r, c.get("/api/google/account")):
            body = resp.text
            assert SECRET not in body and TOKEN not in body and CID not in body
            assert resp.json()["connected"] is True and resp.json()["title"] == "UniC Plaquiste"
        assert c.get("/api/google/status").json()["configured"] is True
        bad = c.put("/api/google/account", json={"client_id": "x", "client_secret": "y", "refresh_token": "z"})
        assert bad.status_code == 400
        d = c.delete("/api/google/account")
        assert d.status_code == 200 and d.json()["connected"] is False
        assert c.get("/api/google/status").json()["configured"] is False


def test_fiche_is_found_in_a_later_account_not_only_the_first():
    FakeHttp.plan["accounts"] = Resp(200, {"accounts": [{"name": "accounts/AAA"}, {"name": "accounts/BBB"}]})
    FakeHttp.plan["by_account"] = {"AAA": Resp(200, {}), "BBB": Resp(200, {"locations": [{"name": "locations/999", "title": "UniC Plaquiste"}]})}
    db = _db()
    try:
        out = google_account.connect(db, CID, SECRET, TOKEN)
        assert out["connected"] and gb._v("gbp_account_id") == "BBB" and gb._v("gbp_location_id") == "999"
    finally:
        db.close()


def test_no_fiche_in_any_account_says_how_many_accounts_were_seen():
    FakeHttp.plan["accounts"] = Resp(200, {"accounts": [{"name": "accounts/AAA"}, {"name": "accounts/BBB"}]})
    FakeHttp.plan["by_account"] = {"AAA": Resp(200, {}), "BBB": Resp(403)}
    db = _db()
    try:
        with pytest.raises(google_account.GoogleAccountError) as e:
            google_account.connect(db, CID, SECRET, TOKEN)
        assert "2 compte(s)" in str(e.value) and "PROPRIÉTAIRE" in str(e.value)
        assert db.get(AppSetting, "gbp_refresh_token") is None
    finally:
        db.close()
