"""Disjoncteur des services extérieurs : seuls les échecs réels comptent, le repos a une fin, chaque service a son compteur."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import connectors, google_business as gbp, mailbox  # noqa: E402
from app.breaker import BREAKER, Breaker, CircuitOpen  # noqa: E402
from app.main import app  # noqa: E402


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def boom(*a, **k):
    raise RuntimeError("panne")


def test_opens_after_threshold_and_stops_calling_the_service():
    clk, b, hits = Clock(), None, []
    b = Breaker(seuil=3, repos=60, clock=clk)

    def fail():
        hits.append(1)
        raise OSError("down")

    for _ in range(3):
        with pytest.raises(OSError):
            b.call("imap", fail)
    with pytest.raises(CircuitOpen) as e:
        b.call("imap", fail)
    assert len(hits) == 3 and e.value.retry_in == 61 and "3 échecs de suite" in str(e.value)   # le 4e appel n'a RIEN tenté


def test_rest_ends_and_a_real_success_closes_it():
    clk = Clock(); b = Breaker(seuil=2, repos=60, clock=clk)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            b.call("imap", boom)
    with pytest.raises(CircuitOpen):
        b.call("imap", lambda: 1)
    clk.t += 61
    assert b.call("imap", lambda: "ok") == "ok"          # vraie chance après le repos
    assert b.status() == {}                              # succès : compteur à zéro
    with pytest.raises(RuntimeError):
        b.call("imap", boom)                              # un seul échec ne ré-ouvre pas
    assert b.call("imap", lambda: 2) == 2


def test_each_service_has_its_own_counter():
    b = Breaker(seuil=1, repos=60, clock=Clock())
    with pytest.raises(RuntimeError):
        b.call("imap", boom)
    with pytest.raises(CircuitOpen):
        b.call("imap", lambda: 1)
    assert b.call("google", lambda: "libre") == "libre"


def test_only_declared_failures_count():
    b = Breaker(seuil=2, repos=60, clock=Clock())
    for _ in range(5):
        with pytest.raises(KeyError):
            b.call("google", lambda: {}["x"], failures=(ValueError,))      # erreur de programme ≠ panne du service
    assert b.status() == {}


def test_invalid_settings_are_refused():
    with pytest.raises(ValueError):
        Breaker(seuil=0)
    with pytest.raises(ValueError):
        Breaker(repos=0)


@pytest.fixture(autouse=True)
def clean():
    BREAKER.reset()
    yield
    BREAKER.reset()


def test_mailbox_calls_are_paused_after_repeated_failures_and_not_hammered(monkeypatch):
    calls = []
    monkeypatch.setattr(mailbox, "imap_configured", lambda: True)
    monkeypatch.setattr(mailbox, "fetch_recent", lambda n: calls.append(n) or (_ for _ in ()).throw(OSError("refusé")))
    from app.database import SessionLocal
    with TestClient(app):
        db = SessionLocal()
        try:
            for _ in range(3):
                with pytest.raises(connectors.ConnectorError) as e:
                    connectors.sync_inbox(db, 5)
                assert e.value.status == 502
            with pytest.raises(connectors.ConnectorError) as e:
                connectors.sync_inbox(db, 5)
            assert e.value.status == 503 and "pause de sécurité" in str(e.value)
            with pytest.raises(connectors.ConnectorError):
                connectors.search_inbox(db, "devis")                          # la recherche partage le même compteur
            assert len(calls) == 3                                           # Gmail n'a été contacté que 3 fois
        finally:
            db.close()


def test_google_calls_are_paused_too(monkeypatch):
    monkeypatch.setattr(connectors, "require_google", lambda: None)
    n = []

    def fn():
        n.append(1)
        raise gbp.GoogleError("Quota Google dépassé")

    for _ in range(3):
        with pytest.raises(connectors.ConnectorError) as e:
            connectors.google_call(fn)
        assert e.value.status == 502
    with pytest.raises(connectors.ConnectorError) as e:
        connectors.google_call(fn)
    assert e.value.status == 503 and len(n) == 3


def test_atelier_data_lists_only_paused_services():
    for _ in range(3):
        BREAKER.failure("imap")
    with TestClient(app) as c:
        d = c.get("/api/selfcare").json()
    assert d["breakers"]["imap"]["open"] is True and d["breakers"]["imap"]["label"] == "La boîte mail" and d["breakers"]["imap"]["retry_in"] > 0
