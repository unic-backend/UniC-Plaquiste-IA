"""Disjoncteur des services extérieurs (Gmail, Google…) : après des échecs RÉELS de suite, on arrête d'essayer un moment.

Idée reprise d'ARENA (`core/execution/disjoncteur.py`), réécrite pour UniC : sans lui, un service tombé ou un mot de passe
refusé refait chaque fois l'appel complet (jusqu'à 20 s d'attente) et peut faire bloquer le compte chez Gmail à force
d'essais. Trois règles :
 1. seul un échec réel du service compte (un service « non connecté » n'est pas un échec : rien n'a été tenté) ;
 2. le repos a une fin : passé `repos`, le prochain appel a une vraie chance (jamais coupé pour de bon sur la foi d'échecs anciens) ;
 3. chaque service a son compteur : Gmail en panne ne coupe pas Google.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

SEUIL = 3        # échecs de suite avant ouverture (en dessous, un seul raté réseau couperait un service sain)
REPOS = 60.0     # secondes d'arrêt avant de redonner sa chance

LABELS = {"imap": "La boîte mail", "google": "La fiche Google"}


class CircuitOpen(Exception):
    """Le service est en pause ; `retry_in` = secondes avant le prochain essai possible."""

    def __init__(self, name: str, fails: int, retry_in: int):
        self.name, self.fails, self.retry_in = name, fails, retry_in
        super().__init__(f"{LABELS.get(name, name)} ne répond pas ({fails} échecs de suite) : pause de sécurité, nouvel essai possible dans {retry_in} s.")


class Breaker:
    def __init__(self, seuil: int = SEUIL, repos: float = REPOS, clock: Callable[[], float] = time.monotonic):
        if seuil < 1 or repos <= 0:
            raise ValueError("seuil >= 1 et repos > 0")
        self.seuil, self.repos, self._clock = seuil, repos, clock
        self._lock = threading.Lock()
        self._s: dict[str, dict[str, Any]] = {}

    def _state(self, name: str) -> dict[str, Any]:
        return self._s.setdefault(name, {"fails": 0, "until": None})

    def before(self, name: str) -> None:
        with self._lock:
            st = self._state(name)
            if st["until"] is None:
                return
            now = self._clock()
            if now < st["until"]:
                raise CircuitOpen(name, st["fails"], int(st["until"] - now) + 1)
            st["until"], st["fails"] = None, 0      # repos terminé : vraie chance au prochain appel

    def success(self, name: str) -> None:
        with self._lock:
            st = self._state(name)
            st["fails"], st["until"] = 0, None

    def failure(self, name: str) -> None:
        with self._lock:
            st = self._state(name)
            st["fails"] += 1
            if st["fails"] >= self.seuil and st["until"] is None:
                st["until"] = self._clock() + self.repos

    def call(self, name: str, fn: Callable[..., Any], *args: Any, failures: tuple[type[BaseException], ...] = (Exception,), **kw: Any) -> Any:
        """Exécute `fn` si le service n'est pas en pause. Seules les exceptions de `failures` comptent comme échec du service."""
        self.before(name)
        try:
            out = fn(*args, **kw)
        except failures:
            self.failure(name)
            raise
        self.success(name)
        return out

    def status(self) -> dict[str, dict[str, Any]]:
        """Pour l'Atelier : uniquement les services avec des échecs récents."""
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            now = self._clock()
            for name, st in self._s.items():
                if st["fails"] <= 0:
                    continue
                open_ = st["until"] is not None and now < st["until"]
                out[name] = {"label": LABELS.get(name, name), "fails": st["fails"], "open": open_,
                             "retry_in": int(st["until"] - now) + 1 if open_ else 0}
        return out

    def reset(self) -> None:
        with self._lock:
            self._s.clear()


BREAKER = Breaker()
