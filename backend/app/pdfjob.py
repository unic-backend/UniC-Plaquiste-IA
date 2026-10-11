"""Lance `pdfworker.py` dans un processus séparé, mémoire et durée bornées : un plan trop lourd ne peut plus faire tomber le serveur."""
from __future__ import annotations

import json
import logging
import resource
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("unic.pdfjob")

WORKER = Path(__file__).with_name("pdfworker.py")
MEMORY_MB = 320   # serveur Render 512 Mo : ~150 Mo pour l'application + ce plafond pour le travail lourd


class PdfJobError(Exception):
    pass


def _limit() -> None:
    lim = MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (lim, lim))


def run(op: str, timeout: int = 90, **kwargs) -> dict:
    try:
        r = subprocess.run([sys.executable, str(WORKER), json.dumps({"op": op, **kwargs})],
                           capture_output=True, text=True, timeout=timeout, preexec_fn=_limit)
    except subprocess.TimeoutExpired as exc:
        logger.error("pdfworker %s : délai dépassé (%s s)", op, timeout)
        raise PdfJobError("Plan trop long à dessiner (délai dépassé).") from exc
    try:
        out = json.loads(r.stdout or "{}")
    except ValueError:
        out = {}
    if not out or out.get("error"):
        logger.error("pdfworker %s : %s (code %s) %s", op, out.get("error"), r.returncode, (r.stderr or "")[-300:])
        raise PdfJobError("Plan trop lourd pour être dessiné par le serveur." if out.get("error") in (None, "memory")
                          else "Lecture du PDF impossible.")
    return out
