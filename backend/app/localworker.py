"""Moteur local sur le PC du patron (Ollama), sans ouvrir son réseau : c'est le PC qui vient chercher le travail.

L'appli UniC AI pour Windows interroge le serveur (POST /api/worker/poll) ; quand Claude ne répond pas, la question est
mise en file, le PC la traite avec son modèle local et renvoie la réponse. PC éteint = rien en file, réponse immédiate
(jamais d'attente inutile). Le modèle local ne voit que le contexte fourni et doit dire quand il ne sait pas.

File et présence du PC en MÉMOIRE (un seul processus serveur) : aucune écriture en base pendant qu'une conversation
est en cours d'enregistrement (SQLite n'accepte qu'un écrivain à la fois).
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

ONLINE_SECONDS = 45      # le PC est « en ligne » s'il a interrogé le serveur il y a moins de 45 s
WAIT_SECONDS = 90        # attente maximale d'une réponse du PC
POLL_HOLD = 20           # le PC attend jusqu'à 20 s qu'une question arrive (moins de requêtes)
MAX_SYSTEM = 12000       # contexte transmis au petit modèle (sa mémoire de travail est courte)

LOCAL_RULES = (
    "\n\nTU ES LE MOTEUR LOCAL DE SECOURS (Claude est indisponible). Tu n'as AUCUN outil : tu ne peux ni créer de devis, "
    "ni lire les mails, ni chercher sur Internet. Réponds en français, court (2 à 6 lignes), UNIQUEMENT avec les informations "
    "présentes ci-dessus (mémoire, base UniC, documents, conversation). Si l'information n'y est pas, réponds exactement : "
    "« Je ne sais pas : Claude est indisponible et je ne l'ai pas en mémoire. » N'invente jamais un prix, un nom, une date ou un chiffre."
)

_cond = threading.Condition()
_queue: list[dict] = []            # questions en attente
_jobs: dict[str, dict] = {}        # id -> {messages, status, result, model, created}
_seen = {"at": 0.0, "model": ""}


def heartbeat(model: str = "") -> None:
    with _cond:
        _seen["at"] = time.time()
        if model:
            _seen["model"] = model[:64]


def status(_db=None) -> dict:
    age = time.time() - _seen["at"] if _seen["at"] else None
    return {"online": bool(age is not None and age < ONLINE_SECONDS), "model": _seen["model"],
            "last_seen": datetime.fromtimestamp(_seen["at"], timezone.utc).isoformat() if _seen["at"] else None}


def online(_db=None) -> bool:
    return status()["online"]


def build_messages(messages: list[dict]) -> list[dict]:
    """Messages pour le petit modèle : consignes de l'IA (tronquées) + règles du secours + derniers échanges."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system" and isinstance(m.get("content"), str))
    turns = [{"role": m["role"], "content": m["content"]} for m in messages
             if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-8:]
    return [{"role": "system", "content": system[:MAX_SYSTEM] + LOCAL_RULES}] + turns


def ask(_db, messages: list[dict], wait: float = WAIT_SECONDS) -> tuple[str, str]:
    """(réponse, modèle) ou ("", "") si le PC est éteint ou trop lent."""
    if not online():
        return "", ""
    jid = uuid.uuid4().hex
    job = {"id": jid, "messages": build_messages(messages), "status": "queued", "result": "", "model": "", "created": time.time()}
    deadline = time.time() + wait
    with _cond:
        _jobs[jid] = job
        _queue.append(job)
        _cond.notify_all()
        while job["status"] not in ("done", "failed") and time.time() < deadline:
            _cond.wait(timeout=max(0.1, deadline - time.time()))
        if job in _queue:
            _queue.remove(job)
        _jobs.pop(jid, None)
    if job["status"] == "done":
        return job["result"].strip(), job["model"]
    return "", ""


def next_job(_db=None, model: str = "", hold: float = POLL_HOLD) -> dict | None:
    """Appelé par le PC : se signale en ligne, prend la plus ancienne question (attend un peu s'il n'y en a pas)."""
    heartbeat(model)
    deadline = time.time() + max(0.0, hold)
    with _cond:
        while True:
            _seen["at"] = time.time()
            if _queue:
                job = _queue.pop(0)
                job["status"] = "taken"
                return {"id": job["id"], "messages": job["messages"]}
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            _cond.wait(timeout=min(remaining, 5))


def finish(_db, job_id: str, text: str, model: str = "", ok: bool = True) -> bool:
    with _cond:
        job = _jobs.get(job_id)
        if job is None or job["status"] != "taken":
            return False
        job["status"] = "done" if ok and (text or "").strip() else "failed"
        job["result"], job["model"] = (text or "")[:20000], (model or "")[:64]
        _cond.notify_all()
    return True


def reset() -> None:
    """Tests : oublie le PC et la file."""
    with _cond:
        _queue.clear()
        _jobs.clear()
        _seen.update(at=0.0, model="")
