"""Agents créés par UniC (ou le patron) : une mission qui tourne seule, à intervalle fixe, avec des outils sûrs.

Un agent lit, vérifie et PRÉPARE (brouillons) ; il n'envoie, ne publie, ne crée ni ne supprime aucun document.
Son rapport arrive dans le briefing et dans l'Atelier. Proposé par l'IA = en attente du clic du patron.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CustomAgent

logger = logging.getLogger("unic.agents")

MAX_ACTIVE = 10
SAFE_TOOLS = {   # lecture et brouillons seulement
    "read_inbox", "read_email", "save_email_reply_draft", "list_google_reviews", "google_profile_audit",
    "save_google_review_reply_draft", "save_social_post_draft", "google_post_plan", "list_social_posts",
    "get_prices", "list_directory", "list_documents", "list_agenda", "list_unpaid", "list_tracking", "list_memory", "quote_margin", "explain_quote",
}
_running: set[str] = set()
_lock = threading.Lock()

# Garde-fous d'un passage (appliqués par le SERVEUR, jamais par le modèle) : un agent ne peut pas s'en donner davantage.
MAX_SECONDS = 120        # durée maximale d'un passage
MAX_TOOL_CALLS = 20      # appels d'outils maximum par passage
GRACE_SECONDS = 15       # délai de grâce avant l'arrêt forcé (le modèle termine son rapport)
MAX_SAME_CALL = 2        # le même appel (même outil, mêmes arguments) au plus 2 fois : au-delà, c'est une boucle
HALT_KEY = "agents_halt"


def halted(db: Session) -> bool:
    """Arrêt d'urgence : tant qu'il est actif, aucun agent ne démarre (même à la main) et ceux en cours s'arrêtent au prochain outil."""
    from app.models import AppSetting
    db.expire_all()
    row = db.get(AppSetting, HALT_KEY)
    return bool(row and row.value == "1")


def set_halt(db: Session, on: bool) -> bool:
    from app.models import AppSetting
    row = db.get(AppSetting, HALT_KEY)
    if row is None:
        db.add(AppSetting(key=HALT_KEY, value="1" if on else "0"))
    else:
        row.value = "1" if on else "0"
    db.commit()
    return on


def tools_for(a: CustomAgent) -> set[str]:
    """Outils autorisés pour CET agent : sa liste (si le patron ou l'IA l'a réduite) ∩ SAFE_TOOLS. Jamais plus que les outils sûrs."""
    try:
        wanted = set(json.loads(a.allowed_tools)) if a.allowed_tools else set()
    except (ValueError, TypeError):
        wanted = set()
    return (wanted & SAFE_TOOLS) if wanted else set(SAFE_TOOLS)


class RunControl:
    """Un passage d'agent : identifiant de corrélation, délai, plafond d'appels, détection de boucle, arrêt d'urgence."""

    def __init__(self, run_id: str, allowed: set[str], max_seconds: float | None = None):
        self.run_id, self.allowed = run_id, allowed
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=MAX_SECONDS if max_seconds is None else max_seconds)
        self.calls = 0
        self.seen: dict[str, int] = {}
        self.stop_reason = ""

    def check(self, db: Session, name: str, args: dict) -> str | None:
        """Raison de refuser cet appel (texte pour le modèle), ou None s'il peut s'exécuter."""
        if self.stop_reason:
            return f"Passage arrêté ({self.stop_reason}) : termine maintenant par ton rapport."
        if halted(db):
            self.stop_reason = "arrêt d'urgence du patron"
        elif datetime.now(timezone.utc) > self.deadline:
            self.stop_reason = "durée maximale atteinte"
        elif name not in self.allowed:
            return "Outil non autorisé pour cet agent."
        else:
            self.calls += 1
            if self.calls > MAX_TOOL_CALLS:
                self.stop_reason = f"plafond de {MAX_TOOL_CALLS} appels d'outils atteint"
            else:
                sig = name + json.dumps(args, sort_keys=True, default=str)
                self.seen[sig] = self.seen.get(sig, 0) + 1
                if self.seen[sig] > MAX_SAME_CALL:
                    self.stop_reason = f"boucle détectée ({name} répété)"
        return f"Passage arrêté ({self.stop_reason}) : termine maintenant par ton rapport." if self.stop_reason else None


def _complete(msgs, **kw):
    """Appel du modèle (isolé ici pour pouvoir être remplacé dans les tests)."""
    from app.ai import ClaudeAIProvider
    return ClaudeAIProvider().complete(msgs, **kw)


class AgentError(ValueError):
    pass


def to_dict(a: CustomAgent) -> dict:
    return {"id": a.id, "name": a.name, "mission": a.mission, "every_hours": a.every_hours, "status": a.status,
            "tools": sorted(tools_for(a)), "last_run_id": a.last_run_id or "",
            "created_by": a.created_by, "runs": a.runs, "last_ok": a.last_ok, "last_result": a.last_result,
            "last_run": a.last_run.isoformat() if a.last_run else None, "running": a.id in _running}


def create(db: Session, name: str, mission: str, every_hours: int = 24, by: str = "ai", active: bool = True,
           tools: list[str] | None = None) -> CustomAgent:
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
    chosen = sorted({str(t) for t in (tools or [])})
    unknown = [t for t in chosen if t not in SAFE_TOOLS]
    if unknown:
        raise AgentError("Outil(s) refusé(s) pour un agent (lecture et brouillons seulement) : " + ", ".join(unknown[:5]))
    a = CustomAgent(name=name, mission=mission, every_hours=every, status=status, created_by=by,
                    allowed_tools=json.dumps(chosen) if chosen else "")
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
        if _due(a, now) and start(a.id):
            started.append(a.name)
    return started


def start(agent_id: str) -> bool:
    from app.database import SessionLocal
    with SessionLocal() as chk:
        if halted(chk):
            return False   # arrêt d'urgence actif : rien ne démarre
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
    """Un passage de l'agent : Claude + outils sûrs, sous garde-fous serveur ; le rapport et le journal des décisions sont gardés."""
    from app import agent as ag
    from app import usage
    from app.config import settings
    from app.database import SessionLocal

    allowed = tools_for(a)
    tools = [t for t in ag.TOOLS if t["name"] in allowed]
    run_id = uuid.uuid4().hex[:12]
    ctl = RunControl(run_id, allowed)
    session = ag.AgentSession(db, None, {}, run_id=run_id)
    session.audit_prefix = f"agent={a.name[:40]} "
    system = (f"Tu es « {a.name} », un agent automatique d'UniC AI (UniC Plaquiste, Dakar). Tu travailles SEUL : le patron "
              "n'est pas en ligne, ne pose aucune question. Fais ta mission avec les outils autorisés (lecture et brouillons "
              "seulement : rien n'est envoyé, publié, créé ni supprimé sans son clic). Ne mets rien d'inventé. "
              f"Tu as au plus {MAX_TOOL_CALLS} appels d'outils et {MAX_SECONDS} secondes ; ne répète jamais le même appel. "
              "Termine par un RAPPORT de 5 lignes maximum, en français simple : ce que tu as trouvé, ce que tu as préparé, "
              "ce que le patron doit faire (ou « Rien à signaler »)." + ag.availability_note(db))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"MISSION : {a.mission}"}]

    def safe(name, args):   # décision du serveur : liste d'outils, plafond, boucle, délai, arrêt d'urgence
        refused = ctl.check(db, name, args if isinstance(args, dict) else {})
        if refused:
            ag.audit(db, None, "agent_tool_refused", "tool", name, f"run={run_id} agent={a.name[:40]} {refused}"[:300])
            db.commit()
            return {"error": refused}
        return session(name, args)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"unic-agent-run-{run_id}")
    res, timeout = None, False
    try:
        fut = executor.submit(_complete, msgs, model=settings.anthropic_fast_model, tools=tools, tool_handler=safe, max_tokens=3000)
        res = fut.result(timeout=MAX_SECONDS + GRACE_SECONDS)
    except FutureTimeout:
        timeout = True
        ctl.stop_reason = ctl.stop_reason or "délai dépassé"   # tout appel d'outil ultérieur est refusé
    finally:
        executor.shutdown(wait=False)
    if res is not None and res.raw:
        try:
            usage.record(db, res.raw.get("usage"), res.model)
        except Exception:
            pass
    with SessionLocal() as fresh:   # état final écrit par une session neuve (le fil du modèle peut encore tenir l'ancienne)
        row = fresh.get(CustomAgent, a.id)
        row.last_run = datetime.now(timezone.utc)
        row.runs = (row.runs or 0) + 1
        row.last_run_id = run_id
        ok = bool(res is not None and res.available and res.text) and not timeout
        row.last_ok = ok
        if ok:
            text = res.text.strip()
            if ctl.stop_reason:
                text = f"⚠️ Passage interrompu ({ctl.stop_reason}). " + text
        elif timeout:
            text = f"Passage arrêté : durée maximale dépassée ({MAX_SECONDS} s)."
        else:
            text = f"Passage échoué : {(res.error if res else '') or 'pas de réponse'}"
        row.last_result = text[:4000]
        ag.audit(fresh, None, "agent_run", "agent", a.id, f"run={run_id} agent={a.name[:40]} ok={ok} appels={ctl.calls} arret={ctl.stop_reason or '-'}")
        fresh.commit()
        last_text = row.last_result
    if not timeout:   # l'objet reçu reflète l'état final (après timeout, le fil du modèle peut encore tenir la session : on n'y touche pas)
        db.refresh(a)
    if not ok:
        from app import selfcare
        selfcare.report(f"agent:{a.name}", f"Agent « {a.name} » : {last_text[:150]}", kind="tool")
    return {"ok": ok, "rapport": last_text, "brouillons": len(session.cards), "run_id": run_id, "arret": ctl.stop_reason}


def journal(db: Session, a: CustomAgent, limit: int = 60) -> list[dict]:
    """Journal des décisions du dernier passage (outils appelés, refusés, résultat), relié par l'identifiant de corrélation."""
    from app.models import AuditLog
    if not a.last_run_id:
        return []
    rows = db.query(AuditLog).filter(AuditLog.details.like(f"run={a.last_run_id}%")).order_by(AuditLog.created_at).limit(limit).all()
    return [{"at": r.created_at.isoformat() if r.created_at else None, "action": r.action, "outil": r.entity_id if r.entity_type == "tool" else "",
             "detail": r.details[:240]} for r in rows]


def recent_reports(db: Session, hours: int = 26) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for a in db.query(CustomAgent).filter(CustomAgent.status == "active").all():
        last = a.last_run if (a.last_run is None or a.last_run.tzinfo) else a.last_run.replace(tzinfo=timezone.utc)
        if last and last >= since and a.last_result:
            out.append({"agent": a.name, "ok": a.last_ok, "rapport": a.last_result[:600]})
    return out
