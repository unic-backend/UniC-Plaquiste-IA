"""Étape 2 du diagnostic : personne ne peut bloquer l'accès du patron ; un long travail ne fige plus l'appli."""
import asyncio
import time

from fastapi.testclient import TestClient

from app import main, sitechat
from app.config import settings


def test_dix_codes_faux_d_un_inconnu_ne_bloquent_pas_le_patron(monkeypatch):
    """Derrière Render, toutes les requêtes arrivent du même relais : le verrou compte désormais par adresse réelle."""
    monkeypatch.setattr(settings, "unic_access_code", "le-bon-code-123")
    main.ratelimit._mem.clear()
    with TestClient(main.app) as c:
        for i in range(10):
            c.get("/api/auth/me", headers={"x-access-code": "faux", "x-forwarded-for": f"203.0.113.{i}"})
        assert c.get("/api/auth/me", headers={"x-access-code": "le-bon-code-123", "x-forwarded-for": "41.82.10.10"}).status_code == 200
        for _ in range(10):                                                         # le même inconnu qui insiste, lui, est bloqué
            c.get("/api/auth/me", headers={"x-access-code": "faux", "x-forwarded-for": "198.51.100.7"})
        assert c.get("/api/auth/me", headers={"x-access-code": "faux", "x-forwarded-for": "198.51.100.7"}).status_code == 429
    main.ratelimit._mem.clear()


def test_un_visiteur_du_site_ne_fige_plus_l_appli(monkeypatch):
    """Le chat public attend Claude plusieurs secondes : pendant ce temps, le reste de l'appli doit répondre."""
    import httpx
    monkeypatch.setattr(settings, "unic_access_code", "")

    def slow_reply(db, session_id, text, ip, page=""):
        time.sleep(1.5)                                                             # Claude qui réfléchit
        return {"session_id": "s", "reply": "Bonjour !", "whatsapp": "", "limited": False}
    monkeypatch.setattr(sitechat, "reply", slow_reply)

    async def scenario():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            chat = asyncio.create_task(c.post("/api/public/chat", json={"message": "Bonjour"}))
            t0 = time.monotonic()
            await asyncio.sleep(0.2)                                                # le visiteur attend déjà sa réponse
            ping = await c.get("/api/ping")
            waited = time.monotonic() - t0
            return (await chat), ping, waited
    chat, ping, waited = asyncio.run(scenario())
    assert chat.json()["reply"] == "Bonjour !" and ping.status_code == 200
    assert waited < 1.0                                                             # avant : 1,5 s et plus, le temps de la réponse du visiteur
