"""UniC se surveille lui-même : journal des problèmes, agents endormis réveillés, contrôle de santé quotidien.

- Toute erreur du serveur (journal Python niveau ERROR) devient un « incident » regroupé par empreinte (même bug = une ligne, compteur).
- Chaque fil de fond (sauvegarde, agents, surveillance) bat un « pouls » ; un pouls arrêté = agent endormi → relancé + incident.
- Le contrôle de santé vérifie base, disque, mémoire, Claude, sauvegardes, agents et incidents ouverts.
- Aucun secret n'entre dans le journal (clés, jetons, mots de passe masqués).
La réparation du code est dans `repair.py` (pull request, fusion au clic du patron).
"""
from __future__ import annotations

import hashlib
import os
import logging
import re
import shutil
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

logger = logging.getLogger("unic.selfcare")

TICK_S = 60
CHECK_EVERY_H = 24
_pending: deque = deque(maxlen=500)          # incidents en attente d'écriture (le journal ne touche jamais la base lui-même)
_beats: dict[str, tuple[float, float]] = {}  # nom → (dernier pouls, intervalle attendu en s)
_restart: dict[str, callable] = {}           # nom → relance
_guard = threading.local()
_SECRET = re.compile(r"(sk-ant-[\w-]+|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[\w]+|Bearer\s+[\w.\-]+|"
                     r"(?i:(?:password|passwd|mot_de_passe|token|secret|api_key|access_code)\s*[=:]\s*)\S+)")


def scrub(text: str) -> str:
    """Masque tout ce qui ressemble à un secret."""
    return _SECRET.sub("[masqué]", text or "")


def fingerprint(source: str, message: str, detail: str = "") -> str:
    frames = re.findall(r'File "([^"]+)", line (\d+)', detail or "")
    last = frames[-1] if frames else ("", "")
    first = (message or "").strip().splitlines()[0][:160] if (message or "").strip() else ""
    first = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}|\d+", "#", first)   # identifiants et nombres variables : même bug
    return hashlib.sha256(f"{source}|{first}|{last[0].rsplit('/', 1)[-1]}:{last[1]}".encode()).hexdigest()[:40]


def report(source: str, message: str, detail: str = "", kind: str = "error") -> None:
    """Signale un problème (sûr depuis n'importe quel fil : écrit plus tard par la surveillance)."""
    _pending.append({"source": source[:120], "message": scrub(message)[:1000], "detail": scrub(detail)[-6000:],
                     "kind": kind, "at": datetime.now(timezone.utc)})


class _IncidentHandler(logging.Handler):
    """Branché sur le journal : chaque erreur du serveur devient un incident."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_guard, "on", False) or record.name.startswith("unic.selfcare"):
            return
        _guard.on = True
        try:
            detail = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg = f"{msg} — {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            report(record.name, msg, detail)
        except Exception:
            pass
        finally:
            _guard.on = False


def install_log_capture() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, _IncidentHandler) for h in root.handlers):
        h = _IncidentHandler(level=logging.ERROR)
        root.addHandler(h)
        for name in ("uvicorn.error", "unic"):
            lg = logging.getLogger(name)
            if not any(isinstance(x, _IncidentHandler) for x in lg.handlers) and not lg.propagate:
                lg.addHandler(h)


def flush(db) -> int:
    """Écrit les incidents en attente (regroupés)."""
    from app.models import Incident
    n = 0
    while _pending:
        it = _pending.popleft()
        fp = fingerprint(it["source"], it["message"], it["detail"])
        row = db.query(Incident).filter(Incident.fingerprint == fp).first()
        if row is None:
            db.add(Incident(fingerprint=fp, kind=it["kind"], source=it["source"], message=it["message"],
                            detail=it["detail"], first_at=it["at"], last_at=it["at"]))
        else:
            row.count += 1
            row.last_at = it["at"]
            row.detail = it["detail"] or row.detail
            if row.status == "fixed":
                row.status = "open"   # « corrigé » mais revenu : on rouvre
        n += 1
        db.flush()
    if n:
        db.commit()
    return n


# ---------- pouls des agents de fond ----------

def beat(name: str, every_s: float, restart=None) -> None:
    _beats[name] = (time.time(), every_s)
    if restart is not None:
        _restart[name] = restart


def sleeping() -> list[dict]:
    now = time.time()
    return [{"agent": n, "silence_min": round((now - t) / 60)} for n, (t, every) in _beats.items() if now - t > every * 2.5 + 60]


def wake_sleepers() -> list[str]:
    woke = []
    for s in sleeping():
        name = s["agent"]
        report(f"agent:{name}", f"Agent « {name} » endormi depuis {s['silence_min']} min", kind="sleeping")
        fn = _restart.get(name)
        if fn is not None:
            try:
                fn()
                _beats[name] = (time.time(), _beats[name][1])
                woke.append(name)
            except Exception as exc:
                report(f"agent:{name}", f"Relance impossible : {type(exc).__name__}", kind="sleeping")
    return woke


# ---------- contrôle de santé ----------

def self_check(db) -> dict:
    """Vérifie ce qui fait tourner l'entreprise. Rend {ok, checks:[{nom, ok, detail}]} ; un échec devient un incident."""
    from app import backup
    from app.capabilities import memory_mb
    from app.config import settings
    from app.models import CustomAgent, Incident

    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"nom": name, "ok": bool(ok), "detail": detail})
        if not ok:
            report(f"check:{name}", f"Contrôle « {name} » en échec : {detail}", kind="check")
        else:   # revenu à la normale : l'incident se ferme seul
            healed.append(f"check:{name}")

    healed: list[str] = []

    try:
        db.execute(text("SELECT 1"))
        add("Base de données", True, "répond")
    except Exception as exc:
        add("Base de données", False, type(exc).__name__)
    try:
        probe = settings.storage_path / ".selfcheck"
        probe.write_text("ok")
        probe.unlink()
        du = shutil.disk_usage(settings.data_path)
        free = du.free / du.total if du.total else 1
        add("Disque", free > 0.10, f"{du.free // (1024 * 1024)} Mo libres ({free:.0%})")
    except Exception as exc:
        add("Disque", False, f"écriture impossible ({type(exc).__name__})")
    mem = memory_mb() or {}
    rss = mem.get("actuelle_mo") or 0
    add("Mémoire", not rss or rss < 430, f"{rss} Mo utilisés sur 512" if rss else "non mesurée")
    add("Claude (cerveau)", bool(settings.anthropic_api_key), "clé présente" if settings.anthropic_api_key else "clé ANTHROPIC_API_KEY absente")
    st = backup.status()
    last = st.get("last_local")
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
    except ValueError:
        age_h = None
    if settings.is_sqlite:
        add("Sauvegarde", age_h is not None and age_h < 30, f"dernière il y a {age_h:.0f} h" if age_h is not None else "aucune sauvegarde encore")
        if st.get("last_remote_error"):
            add("Sauvegarde Gmail", False, st["last_remote_error"][:160])
    sl = sleeping()
    add("Agents de fond", not sl, "tous actifs" if not sl else ", ".join(f"{s['agent']} ({s['silence_min']} min)" for s in sl))
    bad = db.query(CustomAgent).filter(CustomAgent.status == "active", CustomAgent.last_ok.is_(False)).count()
    add("Agents créés", bad == 0, "aucun en échec" if bad == 0 else f"{bad} agent(s) en échec au dernier passage")
    flush(db)
    if healed:
        db.query(Incident).filter(Incident.source.in_(healed), Incident.status == "open").update(
            {Incident.status: "fixed"}, synchronize_session=False)
    open_n = db.query(Incident).filter(Incident.status == "open", Incident.kind == "error").count()
    checks.append({"nom": "Erreurs de code", "ok": open_n == 0, "detail": f"{open_n} à corriger" if open_n else "aucune"})
    from app.models import AppSetting
    row = db.get(AppSetting, "selfcheck_last")
    now = datetime.now(timezone.utc).isoformat()
    if row:
        row.value = now
    else:
        db.add(AppSetting(key="selfcheck_last", value=now))
    flush(db)
    db.commit()
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "at": now}


def _check_due(db) -> bool:
    from app.models import AppSetting
    row = db.get(AppSetting, "selfcheck_last")
    if not row or not row.value:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(row.value) > timedelta(hours=CHECK_EVERY_H)
    except ValueError:
        return True


def incidents(db, status: str = "open", limit: int = 50) -> list[dict]:
    from app.models import Incident
    flush(db)
    q = db.query(Incident)
    if status != "all":
        q = q.filter(Incident.status == status)
    return [to_dict(i) for i in q.order_by(Incident.last_at.desc()).limit(limit).all()]


def to_dict(i, detail: bool = False) -> dict:
    d = {"id": i.id, "kind": i.kind, "source": i.source, "message": i.message, "count": i.count, "status": i.status,
         "fix_url": i.fix_url, "first_at": i.first_at.isoformat() if i.first_at else None,
         "last_at": i.last_at.isoformat() if i.last_at else None}
    if detail:
        d["detail"] = i.detail
    return d


# ---------- boucle de surveillance ----------

def tick() -> None:
    """Un passage : écrit les incidents, réveille les agents endormis, contrôle quotidien, agents créés dus."""
    from app import agents
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        wake_sleepers()
        flush(db)
        if _check_due(db):
            self_check(db)
        agents.run_due(db)
    except Exception:
        logger.exception("Passage de surveillance en échec")
        db.rollback()
    finally:
        db.close()


_started = threading.Event()


def start() -> None:
    """Lance la surveillance (une seule fois)."""
    if _started.is_set():
        return
    _started.set()
    install_log_capture()
    if os.environ.get("UNIC_NO_BACKGROUND"):   # tests : pas de fil de fond, tick() est appelé à la main
        return

    def loop():
        time.sleep(30)
        while True:
            beat("surveillance", TICK_S, restart=_restart_self)
            tick()
            time.sleep(TICK_S)

    threading.Thread(target=loop, name="unic-selfcare", daemon=True).start()


def _restart_self() -> None:
    _started.clear()
    start()


def ensure_running() -> None:
    """Appelé à chaque consultation : si la surveillance elle-même s'est endormie, on la relance."""
    if not _started.is_set():
        return start()
    if any(s["agent"] == "surveillance" for s in sleeping()):
        report("agent:surveillance", "La surveillance s'était arrêtée : relancée", kind="sleeping")
        _restart_self()
