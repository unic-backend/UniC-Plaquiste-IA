"""Limite d'essais ratés : mémoire du processus, Redis (faux), repli si Redis tombe, et source retenue derrière un relais."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import ratelimit  # noqa: E402


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    ratelimit._mem.clear()
    monkeypatch.setattr(ratelimit, "_client", lambda: None)   # par défaut : pas de Redis
    yield
    ratelimit._mem.clear()


def test_blocks_after_the_maximum_of_fails_and_resets_on_success():
    for _ in range(4):
        assert not ratelimit.blocked("ip-a", 5, 900)
        ratelimit.fail("ip-a", 900)
    assert not ratelimit.blocked("ip-a", 5, 900)
    ratelimit.fail("ip-a", 900)
    assert ratelimit.blocked("ip-a", 5, 900)
    assert not ratelimit.blocked("ip-b", 5, 900)                  # une autre source n'est pas touchée
    ratelimit.reset("ip-a")
    assert not ratelimit.blocked("ip-a", 5, 900)


def test_old_fails_expire_with_the_window(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(ratelimit.time, "time", lambda: t["now"])
    for _ in range(5):
        ratelimit.fail("ip-c", 900)
    assert ratelimit.blocked("ip-c", 5, 900)
    t["now"] += 901                                              # 15 minutes plus tard
    assert not ratelimit.blocked("ip-c", 5, 900)
    ratelimit.fail("ip-c", 900)                                  # l'ancien est oublié, pas cumulé
    assert len(ratelimit._mem["ip-c"]) == 1


class FakeRedis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    def get(self, k):
        return self.data.get(k)

    def delete(self, k):
        self.data.pop(k, None)

    def pipeline(self):
        outer = self

        class P:
            def __init__(self):
                self.ops = []

            def incr(self, k):
                self.ops.append(("incr", k))

            def expire(self, k, s):
                self.ops.append(("expire", k, s))

            def execute(self):
                for op in self.ops:
                    if op[0] == "incr":
                        outer.data[op[1]] = int(outer.data.get(op[1], 0)) + 1
                    else:
                        outer.ttl[op[1]] = op[2]
        return P()


def test_redis_counts_are_shared_and_expire_on_the_window(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(ratelimit, "_client", lambda: fake)
    for _ in range(3):
        ratelimit.fail("ip-d", 900)
    assert fake.data["fails:ip-d"] == 3 and fake.ttl["fails:ip-d"] == 900
    assert ratelimit.blocked("ip-d", 3, 900) and not ratelimit.blocked("ip-d", 4, 900)
    ratelimit.reset("ip-d")
    assert "fails:ip-d" not in fake.data and not ratelimit.blocked("ip-d", 3, 900)


def test_if_redis_fails_the_limit_falls_back_to_memory_instead_of_breaking_login(monkeypatch):
    class Broken:
        def get(self, k):
            raise ConnectionError("redis tombé")

        def pipeline(self):
            raise ConnectionError("redis tombé")

        def delete(self, k):
            raise ConnectionError("redis tombé")
    monkeypatch.setattr(ratelimit, "_client", lambda: Broken())
    for _ in range(3):
        ratelimit.fail("ip-e", 900)
    assert ratelimit.blocked("ip-e", 3, 900)                      # le repli mémoire protège toujours
    ratelimit.reset("ip-e")
    assert not ratelimit.blocked("ip-e", 3, 900)


def _req(xff=None, host="10.1.1.1"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host) if host else None)


def test_client_ip_trusts_the_last_forwarded_entry_never_the_first():
    assert ratelimit.client_ip(_req("1.2.3.4, 203.0.113.9")) == "203.0.113.9"      # 1.2.3.4 est écrit par le client
    assert ratelimit.client_ip(_req("203.0.113.9")) == "203.0.113.9"
    assert ratelimit.client_ip(_req(" , 198.51.100.7 ,  ")) == "198.51.100.7"      # espaces et entrées vides ignorés
    assert ratelimit.client_ip(_req(None, host="10.1.1.1")) == "10.1.1.1"           # sans relais : la connexion
    assert ratelimit.client_ip(_req(None, host=None)) == "?"
    assert len(ratelimit.client_ip(_req("x" * 500))) == 64                           # borné : pas de clé géante en mémoire
