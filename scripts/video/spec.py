"""Scénario d'une vidéo (JSON) : validation stricte, partagée par make.py. Le scénario vient de l'appli (donc de Claude) : on ne lui fait pas confiance."""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

SEL_RE = re.compile(r"^[#.][A-Za-z][\w-]{0,40}$")
HOST_OK = re.compile(r"^([a-z0-9-]+\.)*(unicplaquiste\.com|netlify\.app)$")
CTRL = re.compile(r"[\x00-\x1f\x7f<>]")
MAX_CHAPTERS, MAX_END_LINES = 8, 6


def _txt(v, n: int) -> str:
    return CTRL.sub("", str(v or "")).strip()[:n]


def clean(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("scénario invalide")
    u = urlparse(str(raw.get("url") or ""))
    local = os.environ.get("VIDEO_ALLOW_LOCAL") == "1" and u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
    if not local and not (u.scheme == "https" and u.hostname and HOST_OK.match(u.hostname) and not u.username):
        raise ValueError("adresse refusée : seul unicplaquiste.com (ou un aperçu Netlify) est filmé")
    title = [_txt(x, 16).upper() for x in (raw.get("title") or [])][:2] or ["UNIC", "PLAQUISTE"]
    chapters = []
    for c in (raw.get("chapters") or [])[:MAX_CHAPTERS]:
        sel = str((c or {}).get("selector") or "")
        if not SEL_RE.match(sel):
            raise ValueError(f"sélecteur refusé : {sel[:30]}")
        try:
            sec = float((c or {}).get("seconds"))
        except (TypeError, ValueError):
            sec = 4.0
        chapters.append({"selector": sel, "label": _txt(c.get("label"), 24) or "Suite", "seconds": min(9.0, max(2.5, sec))})
    if not chapters:
        raise ValueError("aucun chapitre")
    end = [_txt(x, 60) for x in (raw.get("end") or [])][:MAX_END_LINES]
    return {"url": str(raw["url"]), "title": title, "subtitle": _txt(raw.get("subtitle"), 32).upper(),
            "hero_seconds": min(6.0, max(2.0, float(raw.get("hero_seconds") or 4.4))), "chapters": chapters, "end": end}
