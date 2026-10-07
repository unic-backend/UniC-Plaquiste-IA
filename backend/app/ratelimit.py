"""Limite d'essais ratés par IP. Redis si REDIS_URL est défini (partagé entre instances), sinon mémoire du processus."""
from __future__ import annotations

import logging
import time

from app.config import settings

logger = logging.getLogger("unic.ratelimit")
_mem: dict[str, list[float]] = {}
_redis = None
_redis_tried = False


def _client():
    global _redis, _redis_tried
    if _redis_tried:
        return _redis
    _redis_tried = True
    if settings.redis_url:
        try:
            import redis
            _redis = redis.Redis.from_url(settings.redis_url, socket_timeout=1.0, decode_responses=True)
            _redis.ping()
        except Exception:
            logger.exception("Redis indisponible : limite en mémoire")
            _redis = None
    return _redis


def blocked(key: str, max_fails: int, window: float) -> bool:
    r = _client()
    if r is not None:
        try:
            return int(r.get(f"fails:{key}") or 0) >= max_fails
        except Exception:
            pass
    now = time.time()
    return len([t for t in _mem.get(key, []) if now - t < window]) >= max_fails


def fail(key: str, window: float) -> None:
    r = _client()
    if r is not None:
        try:
            p = r.pipeline()
            p.incr(f"fails:{key}")
            p.expire(f"fails:{key}", int(window))
            p.execute()
            return
        except Exception:
            pass
    now = time.time()
    _mem[key] = [t for t in _mem.get(key, []) if now - t < window] + [now]


def reset(key: str) -> None:
    r = _client()
    if r is not None:
        try:
            r.delete(f"fails:{key}")
        except Exception:
            pass
    _mem.pop(key, None)
