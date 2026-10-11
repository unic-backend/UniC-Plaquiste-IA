"""Alertes : prévenir le patron quand quelque chose casse, sans qu'il ait à ouvrir l'application.

Constat du diagnostic d'octobre 2026 : les incidents étaient bien enregistrés (`Incident`, écrits par
`selfcare`), mais **aucun canal ne prévenait personne**. Un incident critique découvert trois jours plus tard,
c'est une panne silencieuse — le premier ennemi d'une surveillance, c'est de ne pas être prévenu.

Règles (volontairement strictes) :

- **Destinataire unique : le patron.** L'adresse vient des réglages de l'entreprise (ou du compte d'envoi), donc
  du serveur ; elle n'est JAMAIS lue dans un incident, un e-mail ou un document. Un incident dont le texte
  contient une adresse ne peut pas détourner l'alerte vers un tiers.
- **Une seule alerte par problème** (empreinte mémorisée) et un **plafond quotidien** : pas de tempête de messages
  qui finirait ignorée. Les problèmes déjà connus ne sont pas répétés à chaque tour.
- **Rien ne part sans le clic du propriétaire** (règle d'AGENTS.md) : les alertes sont DÉSACTIVÉES tant que le patron ne les active
  pas (Atelier › Alertes). `UNIC_ALERTS_ENABLED=false` les coupe quoi qu'il arrive.
- **Rien ne part sans SMTP configuré** (Paramètres › Courrier).
- **Aucun secret** : le texte des incidents est déjà nettoyé par `selfcare.scrub` avant d'être enregistré.
- Le message est **interne** (un courrier au patron, jamais à un client, jamais une publication) : il informe,
  il ne déclenche aucune action sur les documents.

Pourquoi un module séparé : `selfcare.py` (surveillance) est une zone protégée (AGENTS.md) — ce module
**lit** ses incidents, il ne le modifie pas. La coupure se fait par variable d'environnement plutôt que par
`config.py`, lui aussi protégé.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import mailbox
from app.config import settings
from app.models import AppSetting, CompanySettings, Incident

logger = logging.getLogger("unic.alerts")

STATE_KEY = "alerts_state"
MAX_PER_DAY = 8          # plafond de messages par jour : au-delà, le patron aurait arrêté de les lire
CHECK_SECONDS = 300      # un tour toutes les 5 minutes
MAX_LISTED = 12          # problèmes détaillés dans un message (le reste est compté)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

KIND_LABEL = {
    "error": "erreur du serveur",
    "sleeping": "fil de fond arrêté",
    "check": "contrôle en échec",
    "tool": "outil",
}


SETTING_KEY = "alerts_enabled"


def forced_off() -> bool:
    """Coupe-circuit : `UNIC_ALERTS_ENABLED=false` coupe toutes les alertes, quoi qu'ait choisi le patron."""
    return (os.environ.get("UNIC_ALERTS_ENABLED", "") or "").strip().lower() in ("false", "0", "non", "off")


def enabled(db: Session) -> bool:
    """Actives seulement si le patron les a activées (clic dans l'Atelier) ET que le coupe-circuit n'est pas posé."""
    if forced_off():
        return False
    row = db.get(AppSetting, SETTING_KEY)
    return bool(row and (row.value or "") == "1")


def set_enabled(db: Session, on: bool) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value="1" if on else "0"))
    else:
        row.value = "1" if on else "0"
    db.flush()


def _mask(addr: str) -> str:
    name, _, dom = addr.partition("@")
    return (name[:1] + "***@" + dom) if name and dom else ""


def status(db: Session) -> dict:
    """État pour l'Atelier : actives ou non, envoi configuré, adresse (masquée) du patron, messages du jour."""
    st = _state(db)
    today = datetime.now(timezone.utc).date().isoformat()
    return {"enabled": enabled(db), "forced_off": forced_off(), "smtp": mailbox.smtp_configured(),
            "to": _mask(owner_address(db)), "sent_today": st["sent_today"] if st["day"] == today else 0, "max_per_day": MAX_PER_DAY}


def owner_address(db: Session) -> str:
    """Adresse du patron (jamais celle d'un tiers) : réglages de l'entreprise, sinon compte d'envoi."""
    row = db.query(CompanySettings).first()
    for candidate in ((row.email if row else "") or "", settings.smtp_from or "", settings.smtp_user or ""):
        addr = (candidate or "").strip()
        if EMAIL_RE.match(addr):
            return addr
    return ""


def _state(db: Session) -> dict:
    row = db.get(AppSetting, STATE_KEY)
    if row is None:
        return {"alerted": {}, "day": "", "sent_today": 0}
    try:
        data = json.loads(row.value or "{}")
        return {"alerted": dict(data.get("alerted") or {}), "day": data.get("day") or "",
                "sent_today": int(data.get("sent_today") or 0)}
    except (ValueError, TypeError):
        return {"alerted": {}, "day": "", "sent_today": 0}


def _save(db: Session, state: dict) -> None:
    # on ne garde que les 500 dernières empreintes : le fichier de réglages ne grossit pas sans fin
    alerted = dict(list(state["alerted"].items())[-500:])
    state = {**state, "alerted": alerted}
    value = json.dumps(state, ensure_ascii=False)
    row = db.get(AppSetting, STATE_KEY)
    if row is None:
        db.add(AppSetting(key=STATE_KEY, value=value))
    else:
        row.value = value
    db.flush()


def pending(db: Session) -> list[Incident]:
    """Problèmes ouverts jamais annoncés (les plus récents d'abord)."""
    state = _state(db)
    known = state["alerted"]
    rows = db.query(Incident).filter(Incident.status == "open").order_by(Incident.last_at.desc()).all()
    return [i for i in rows if i.fingerprint not in known]


def compose(items: list[Incident], link: str = "") -> tuple[str, str]:
    """Objet et corps du message. Aucune donnée client : uniquement ce que la surveillance a vu."""
    n = len(items)
    subject = f"UniC AI — {n} problème{'s' if n > 1 else ''} à regarder"
    lines = [f"UniC AI a détecté {n} problème{'s' if n > 1 else ''}.", ""]
    for it in items[:MAX_LISTED]:
        when = it.last_at.isoformat(timespec="minutes") if it.last_at else ""
        label = KIND_LABEL.get(it.kind, it.kind)
        lines.append(f"- [{label}] {it.source or 'sans source'} : {(it.message or '(sans détail)')[:200]}")
        lines.append(f"  vu {it.count} fois, dernière fois le {when}")
    if n > MAX_LISTED:
        lines.append(f"- … et {n - MAX_LISTED} autre(s) problème(s), voir l'Atelier.")
    lines += ["", "Ouvre l'application : Atelier › Surveillance (liste, correctif proposé, réparation)."]
    if link:
        lines.append(f"{link.rstrip('/')}/atelier")
    lines += ["", "Message automatique de surveillance (activé par toi). Il n'a rien modifié."]
    return subject, "\n".join(lines)


def send_pending(db: Session, sender=None) -> dict:
    """Envoie au patron un message regroupant les nouveaux problèmes. Rend ce qui a été fait."""
    sender = sender or mailbox.send
    out = {"sent": False, "count": 0, "reason": ""}
    if not enabled(db):
        out["reason"] = "alertes désactivées (à activer dans l'Atelier)"
        return out
    items = pending(db)
    if not items:
        return out
    if not mailbox.smtp_configured():
        out["reason"] = "aucun envoi configuré (Paramètres › Courrier)"
        return out
    to_addr = owner_address(db)
    if not to_addr:
        out["reason"] = "aucune adresse pour le patron"
        return out

    state = _state(db)
    today = datetime.now(timezone.utc).date().isoformat()
    if state["day"] != today:
        state["day"], state["sent_today"] = today, 0
    if state["sent_today"] >= MAX_PER_DAY:
        out["reason"] = f"plafond de {MAX_PER_DAY} messages par jour atteint"
        return out

    subject, body = compose(items, link=settings.unic_public_url or "")
    try:
        sender(to_addr, subject, body)
    except Exception as exc:                       # réseau, mot de passe expiré… : on n'insiste pas, on réessaiera
        logger.warning("Alerte non envoyée à %s : %s: %s", to_addr, type(exc).__name__, exc)
        out["reason"] = f"envoi impossible ({type(exc).__name__})"
        return out

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for it in items:
        state["alerted"][it.fingerprint] = now
    state["sent_today"] += 1
    _save(db, state)
    db.commit()
    logger.info("Alerte envoyée à %s : %d problème(s)", to_addr, len(items))
    return {"sent": True, "count": len(items), "reason": ""}


def tick(db: Session) -> dict:
    """Un tour de surveillance des alertes (lancé par le fil de fond, ou à la main dans les tests)."""
    try:
        from app import selfcare
        selfcare.flush(db)     # les incidents en attente deviennent annonçables sans attendre le tour suivant
    except Exception:
        pass
    return send_pending(db)


_stop = threading.Event()


def start() -> None:
    """Fil discret : regarde les nouveaux problèmes toutes les 5 minutes (jamais en test)."""
    if os.environ.get("UNIC_NO_BACKGROUND"):
        return
    if getattr(start, "_running", False):
        return
    start._running = True   # type: ignore[attr-defined]

    def loop():
        from app.database import SessionLocal
        while not _stop.is_set():
            db = SessionLocal()
            try:
                tick(db)
            except Exception:
                logger.exception("Tour d'alertes en échec")
            finally:
                db.close()
            _stop.wait(CHECK_SECONDS)

    threading.Thread(target=loop, name="unic-alerts", daemon=True).start()
    logger.info("Alertes : surveillance active (une alerte par problème, %d messages par jour au maximum)", MAX_PER_DAY)
