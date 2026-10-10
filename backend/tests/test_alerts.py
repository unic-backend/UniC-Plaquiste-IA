"""Alertes de surveillance : un courrier interne au patron, jamais à un tiers.

Constat du diagnostic d'octobre 2026 : les incidents étaient enregistrés mais aucun canal ne prévenait.
Ces tests vérifient surtout les garde-fous : destinataire impossible à détourner, une seule alerte par
problème, plafond quotidien, coupure par variable d'environnement, et rien du tout sans envoi configuré.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
os.environ.setdefault("UNIC_SECRET_KEY", "test-secret-key-not-for-prod")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def env(monkeypatch):
    """Envoi configuré, alertes actives, un espion à la place du vrai SMTP, et un état vierge.

    La base de test est partagée : les incidents déjà présents (autres tests, exécution précédente) sont
    marqués « déjà annoncés » pour que chaque test ne voie que les problèmes qu'il crée lui-même.
    """
    from app import alerts, mailbox
    from app.database import SessionLocal
    from app.models import AppSetting, Incident, utcnow
    sent: list[tuple[str, str, str]] = []
    db = SessionLocal()
    try:
        connus = {i.fingerprint: utcnow().isoformat(timespec="seconds")
                  for i in db.query(Incident).filter(Incident.status == "open").all()}
        row = db.get(AppSetting, alerts.STATE_KEY)
        if row is None:
            row = AppSetting(key=alerts.STATE_KEY, value="")
            db.add(row)
            db.flush()
        row.value = json.dumps({"alerted": connus, "day": utcnow().date().isoformat(), "sent_today": 0})
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(mailbox, "smtp_configured", lambda: True)
    monkeypatch.setattr(alerts.mailbox, "smtp_configured", lambda: True)
    monkeypatch.delenv("UNIC_ALERTS_ENABLED", raising=False)
    db = SessionLocal()
    try:
        alerts.set_enabled(db, True)    # le patron a activé les alertes (clic dans l'Atelier)
        db.commit()
    finally:
        db.close()
    yield sent
    db = SessionLocal()
    try:
        alerts.set_enabled(db, False)   # état d'origine : désactivées
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def owner(client, monkeypatch):
    """Adresse du patron fixée dans les réglages, restauration ensuite."""
    from app.database import SessionLocal
    from app.models import CompanySettings
    db = SessionLocal()
    row = db.query(CompanySettings).first()
    before = row.email if row else None
    if row is None:
        row = CompanySettings()
        db.add(row)
    row.email = "patron@unicplaquiste.com"
    db.commit()
    db.close()
    yield "patron@unicplaquiste.com"
    db = SessionLocal()
    row = db.query(CompanySettings).first()
    if row is not None:
        row.email = before or ""
        db.commit()
    db.close()


def _incident(message: str, kind: str = "error", status: str = "open") -> str:
    """Crée un vrai incident en base (comme le ferait la surveillance) et rend son empreinte."""
    from app.database import SessionLocal
    from app.models import Incident
    fp = f"test-{uuid.uuid4().hex}"
    db = SessionLocal()
    db.add(Incident(fingerprint=fp, kind=kind, source="test:alertes", message=message, detail="", status=status))
    db.commit()
    db.close()
    return fp


def _run(sent: list) -> dict:
    from app import alerts
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        alerts.send_pending(db, sender=lambda to, subject, body: sent.append((to, subject, body)))
        return {"sent": sent}
    finally:
        db.close()


def test_a_new_problem_warns_the_owner_once(client, env, owner):
    """Un problème nouveau part au patron ; le même problème n'est jamais réannoncé."""
    _incident(f"Erreur de test {uuid.uuid4().hex[:6]}")
    from app import alerts
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert result["sent"] is True and result["count"] >= 1
        assert env and env[0][0] == owner, "l'alerte part au patron"
        assert "problème" in env[0][1]
        # deuxième tour : plus rien (une seule alerte par problème)
        again = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert again["sent"] is False or again["count"] == 0
        assert len(env) == 1, f"le même problème a été réannoncé : {len(env)} envois"
    finally:
        db.close()


def test_the_recipient_is_never_taken_from_the_incident(client, env, owner):
    """Même si un incident contient une adresse, l'alerte va au patron et à personne d'autre."""
    from app import alerts
    from app.database import SessionLocal
    _incident("Contact pirate@ailleurs.example — fuite imaginaire")
    db = SessionLocal()
    try:
        alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert env, "l'alerte devait partir"
        adresses = {to for to, _s, _b in env}
        assert adresses == {owner}
        assert not any("ailleurs.example" in to for to, _s, _b in env)
    finally:
        db.close()


def test_a_closed_problem_does_not_warn(client, env, owner):
    """Un problème déjà corrigé ou ignoré ne réveille personne."""
    from app import alerts
    from app.database import SessionLocal
    _incident(f"Problème déjà réglé {uuid.uuid4().hex[:6]}", status="fixed")
    _incident(f"Problème ignoré {uuid.uuid4().hex[:6]}", status="ignored")
    db = SessionLocal()
    try:
        alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert not env, "un problème fermé ne doit pas déclencher d'alerte"
    finally:
        db.close()


def test_the_switch_stops_everything(client, env, owner, monkeypatch):
    """`UNIC_ALERTS_ENABLED=false` : aucune alerte, quoi qu'il arrive."""
    from app import alerts
    from app.database import SessionLocal
    _incident(f"Erreur pendant la coupure {uuid.uuid4().hex[:6]}")
    monkeypatch.setenv("UNIC_ALERTS_ENABLED", "false")
    db = SessionLocal()
    try:
        out = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert out["sent"] is False and not env
        assert "désactivées" in out["reason"]
    finally:
        db.close()


def test_nothing_is_sent_without_a_configured_sender(client, env, owner, monkeypatch):
    """Sans SMTP (Paramètres › Courrier), on n'invente pas un envoi : on ne fait rien."""
    from app import alerts, mailbox
    from app.database import SessionLocal
    _incident(f"Erreur sans envoi configuré {uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(mailbox, "smtp_configured", lambda: False)
    monkeypatch.setattr(alerts.mailbox, "smtp_configured", lambda: False)
    db = SessionLocal()
    try:
        out = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert out["sent"] is False and not env
        assert "envoi" in out["reason"]
    finally:
        db.close()


def test_a_failed_send_is_retried_later(client, env, owner):
    """Si l'envoi échoue, le problème reste à annoncer : la panne d'e-mail ne doit pas perdre l'alerte."""
    from app import alerts
    from app.database import SessionLocal
    fp = _incident(f"Erreur avec envoi cassé {uuid.uuid4().hex[:6]}")
    db = SessionLocal()
    try:
        def boom(to, subject, body):
            raise OSError("smtp injoignable")

        first = alerts.send_pending(db, sender=boom)
        assert first["sent"] is False and "envoi impossible" in first["reason"]
        assert fp in {i.fingerprint for i in alerts.pending(db)}, "le problème doit rester à annoncer"
        ok = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert ok["sent"] is True and env
    finally:
        db.close()


def test_daily_cap_holds(client, env, owner, monkeypatch):
    """Le plafond quotidien empêche une tempête de messages (que le patron cesserait de lire)."""
    from app import alerts
    from app.database import SessionLocal
    monkeypatch.setattr(alerts, "MAX_PER_DAY", 2)
    db = SessionLocal()
    try:
        for _ in range(3):
            _incident(f"Erreur de série {uuid.uuid4().hex[:6]}")
            alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert len(env) == 2, f"{len(env)} envois pour un plafond de 2"
        out = alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert out["sent"] is False and "plafond" in out["reason"]
    finally:
        db.close()


def test_the_message_never_contains_a_secret(client, env, owner):
    """Le corps du message ne contient aucun secret (nettoyage de la surveillance + le nôtre)."""
    from app import alerts, selfcare
    from app.database import SessionLocal
    fake = "sk-ant-" + "A" * 28
    _incident(f"Clé refusée : {selfcare.scrub('clé ' + fake)}")
    db = SessionLocal()
    try:
        alerts.send_pending(db, sender=lambda to, subject, body: env.append((to, subject, body)))
        assert env
        assert fake not in env[0][2], "un secret ne doit jamais partir par courrier"
    finally:
        db.close()


def test_no_thread_is_started_in_tests(monkeypatch):
    """En test (UNIC_NO_BACKGROUND), aucun fil de fond ne démarre."""
    import threading

    from app import alerts
    before = threading.active_count()
    monkeypatch.setenv("UNIC_NO_BACKGROUND", "1")
    alerts.start()
    assert threading.active_count() == before


def test_alerts_are_off_until_the_owner_turns_them_on(client, env, owner):
    """Règle d'AGENTS.md : rien ne part sans le clic du propriétaire. Par défaut, aucune alerte, même avec un envoi configuré."""
    from app import alerts
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        alerts.set_enabled(db, False)
        db.commit()
    finally:
        db.close()
    _incident("problème pendant que les alertes sont éteintes")
    out = _run(env)
    assert out["sent"] == [] and not alerts_enabled_now()


def alerts_enabled_now() -> bool:
    from app import alerts
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        return alerts.enabled(db)
    finally:
        db.close()


def test_owner_can_turn_alerts_on_and_off_from_the_api(client, env, owner):
    from app import alerts
    st = client.get("/api/alerts").json()
    assert set(st) >= {"enabled", "forced_off", "smtp", "to", "sent_today", "max_per_day"}
    off = client.put("/api/alerts", json={"enabled": False}).json()
    assert off["enabled"] is False
    on = client.put("/api/alerts", json={"enabled": True}).json()
    assert on["enabled"] is True and "@" in on["to"] and on["to"].count("*") == 3   # adresse masquée
    assert alerts.forced_off() is False


def test_the_kill_switch_beats_the_owner_choice(client, env, owner, monkeypatch):
    monkeypatch.setenv("UNIC_ALERTS_ENABLED", "false")
    client.put("/api/alerts", json={"enabled": True})
    assert client.get("/api/alerts").json()["enabled"] is False
