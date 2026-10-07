"""Agents créés par UniC (ou le patron) : une mission qui tourne seule, à intervalle fixe, avec des outils sûrs.

Un agent lit, vérifie et PRÉPARE (brouillons) ; il n'envoie, ne publie, ne crée ni ne supprime aucun document.
Son rapport arrive dans le briefing et dans l'Atelier. Proposé par l'IA = en attente du clic du patron.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CustomAgent

logger = logging.getLogger("unic.agents")

MAX_ACTIVE = 10
SAFE_TOOLS = {   # lecture et brouillons seulement
    "read_inbox", "read_email", "save_email_reply_draft", "list_google_reviews", "google_profile_audit",
    "save_google_review_reply_draft", "save_social_post_draft", "google_post_plan", "list_social_posts",
    "get_prices", "list_directory", "list_documents", "list_agenda", "list_unpaid", "list_tracking", "list_memory",
}
_running: set[str] = set()
_lock = threading.Lock()


class AgentError(ValueError):
    pass


def to_dict(a: CustomAgent) -> dict:
    return {"id": a.id, "name": a.name, "mission": a.mission, "every_hours": a.every_hours, "status": a.status,
            "created_by": a.created_by, "runs": a.runs, "last_ok": a.last_ok, "last_result": a.last_result,
            "last_run": a.last_run.isoformat() if a.last_run else None, "running": a.id in _running}


def create(db: Session, name: str, mission: str, every_hours: int = 24, by: str = "ai", active: bool = True) -> CustomAgent:
    name, mission = (name or "").strip()[:80], (mission or "").strip()[:2000]
    if len(name) < 3 or len(mission) < 20:
        raise AgentError("Donne un nom (3 lettres min.) et une mission claire (une ou deux phrases).")
    try:
        every = max(1, min(int(every_hours or 24), 168))
    except (TypeError, ValueError):
        every = 24
    if db.query(CustomAgent).filter(CustomAgent.name == name).first():
        raise AgentError(f"Un agent « {name} » existe déjà.")
    status = "active" if active else "proposed"
    if status == "active" and db.query(CustomAgent).filter(CustomAgent.status == "active").count() >= MAX_ACTIVE:
        raise AgentError(f"{MAX_ACTIVE} agents actifs au maximum : mets-en un en pause d'abord.")
    a = CustomAgent(name=name, mission=mission, every_hours=every, status=status, created_by=by)
    db.add(a)
    db.commit()
    return a


def set_status(db: Session, a: CustomAgent, status: str) -> CustomAgent:
    if status not in ("active", "paused"):
        raise AgentError("Statut inconnu.")
    if status == "active" and a.status != "active" and \
            db.query(CustomAgent).filter(CustomAgent.status == "active").count() >= MAX_ACTIVE:
        raise AgentError(f"{MAX_ACTIVE} agents actifs au maximum.")
    a.status = status
    db.commit()
    return a


def _due(a: CustomAgent, now: datetime) -> bool:
    if a.status != "active" or a.id in _running:
        return False
    if a.last_run is None:
        return True
    last = a.last_run if a.last_run.tzinfo else a.last_run.replace(tzinfo=timezone.utc)
    return now - last >= timedelta(hours=a.every_hours)


def run_due(db: Session) -> list[str]:
    """Lance (en fond) les agents dont c'est l'heure."""
    now = datetime.now(timezone.utc)
    started = []
    for a in db.query(CustomAgent).filter(CustomAgent.status == "active").all():
        if _due(a, now):
            start(a.id)
            started.append(a.name)
    return started


def start(agent_id: str) -> bool:
    with _lock:
        if agent_id in _running:
            return False
        _running.add(agent_id)
    threading.Thread(target=_run_thread, args=(agent_id,), name=f"unic-agent-{agent_id[:8]}", daemon=True).start()
    return True


def _run_thread(agent_id: str) -> None:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        a = db.get(CustomAgent, agent_id)
        if a is not None:
            run(db, a)
    except Exception:
        logger.exception("Agent %s en échec", agent_id)
    finally:
        _running.discard(agent_id)
        db.close()


def run(db: Session, a: CustomAgent) -> dict:
    """Un passage de l'agent : Claude + outils sûrs ; le rapport est gardé."""
    from app import agent as ag
    from app import usage
    from app.ai import ClaudeAIProvider
    from app.config import settings

    tools = [t for t in ag.TOOLS if t["name"] in SAFE_TOOLS]
    session = ag.AgentSession(db, None, {})
    system = (f"Tu es « {a.name} », un agent automatique d'UniC AI (UniC Plaquiste, Dakar). Tu travailles SEUL : le patron "
              "n'est pas en ligne, ne pose aucune question. Fais ta mission avec les outils autorisés (lecture et brouillons "
              "seulement : rien n'est envoyé, publié, créé ni supprimé sans son clic). Ne mets rien d'inventé. "
              "Termine par un RAPPORT de 5 lignes maximum, en français simple : ce que tu as trouvé, ce que tu as préparé, "
              "ce que le patron doit faire (ou « Rien à signaler »)." + ag.availability_note(db))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"MISSION : {a.mission}"}]
    def safe(name, args):   # un agent n'appelle jamais un outil hors de sa liste
        return session(name, args) if name in SAFE_TOOLS else {"error": "Outil non autorisé pour un agent."}

    res = ClaudeAIProvider().complete(msgs, model=settings.anthropic_fast_model, tools=tools, tool_handler=safe, max_tokens=3000)
    if res.raw:
        try:
            usage.record(db, res.raw.get("usage"), res.model)
        except Exception:
            pass
    a.last_run = datetime.now(timezone.utc)
    a.runs = (a.runs or 0) + 1
    a.last_ok = bool(res.available and res.text)
    a.last_result = (res.text.strip() if a.last_ok else f"Passage échoué : {res.error or 'pas de réponse'}")[:4000]
    db.commit()
    if not a.last_ok:
        from app import selfcare
        selfcare.report(f"agent:{a.name}", f"Agent « {a.name} » : {res.error or 'pas de réponse'}", kind="tool")
    return {"ok": a.last_ok, "rapport": a.last_result, "brouillons": len(session.cards)}


def recent_reports(db: Session, hours: int = 26) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for a in db.query(CustomAgent).filter(CustomAgent.status == "active").all():
        last = a.last_run if (a.last_run is None or a.last_run.tzinfo) else a.last_run.replace(tzinfo=timezone.utc)
        if last and last >= since and a.last_result:
            out.append({"agent": a.name, "ok": a.last_ok, "rapport": a.last_result[:600]})
    return out
