"""Entrées hostiles sur les routes ajoutées cette nuit : jamais d'erreur 500, jamais de secret dans la réponse."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

HOSTILE = ["", " ", "a" * 5000, "x\x00y", "‮\u0000", "'; DROP TABLE users;--", "{{7*7}}", "\\" * 300, "é" * 300, "null", "-1", "1e999"]


class Boom:
    """Tout appel réseau échoue comme une panne : les routes doivent répondre proprement."""
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        raise httpx.ConnectError("hors ligne")

    get = post


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(httpx, "Client", Boom)


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("q", range(len(HOSTILE)))
def test_mail_search_never_500(c, q):
    r = c.get("/api/mail/search", params={"q": HOSTILE[q]})
    assert r.status_code != 500, (q, r.status_code, r.text[:120])   # 503 « IMAP non configuré » est une réponse propre


@pytest.mark.parametrize("q", range(len(HOSTILE)))
def test_search_query_is_one_safe_quoted_line(q):
    from app import mailbox
    out = mailbox._quoted(HOSTILE[q])
    inner = out[1:-1]
    assert out[0] == out[-1] == '"' and len(inner) <= 400
    assert all(ch.isprintable() or ch == " " for ch in inner)          # ni NUL, ni retour à la ligne, ni contrôle
    assert '"' not in inner.replace('\\"', "").replace("\\\\", "")     # tout guillemet est échappé


@pytest.mark.parametrize("i", range(len(HOSTILE)))
def test_google_connect_never_500_and_no_echo(c, i):
    v = HOSTILE[i]
    r = c.put("/api/google/account", json={"client_id": v, "client_secret": v, "refresh_token": v})
    assert r.status_code != 500, (i, r.status_code, r.text[:120])
    if len(v) > 20 and r.status_code != 422:   # le 422 standard de FastAPI cite la valeur refusée, à son seul expéditeur
        assert v not in r.text


@pytest.mark.parametrize("body", [None, [], "x", 5, {"client_id": 5}, {"client_id": None, "client_secret": None, "refresh_token": None}])
def test_google_connect_wrong_types(c, body):
    r = c.put("/api/google/account", json=body)
    assert r.status_code != 500


def test_book_routes_without_site_connection(c):
    assert c.get("/api/book/preview").status_code != 500
    assert c.post("/api/book/publish").status_code != 500
