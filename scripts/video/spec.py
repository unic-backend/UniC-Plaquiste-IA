"""Scénario d'une vidéo (JSON) : validation stricte, partagée par make.py. Le scénario vient de l'appli (donc de Claude) : on ne lui fait pas confiance.

Forme : {"format": "vertical|horizontal|square", "scenes": [ {type: title|text|photo|gallery|stats|quote|page|outro, seconds, ...}, ... ]}
Ancienne forme (url + chapters) acceptée : convertie en titre + page + fin.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

FORMATS = {"vertical": (360, 640), "horizontal": (640, 360), "square": (360, 360)}       # px CSS ; ×3 = 1080×1920, 1920×1080, 1080×1080
SEL_RE = re.compile(r"^[#.][A-Za-z][\w-]{0,40}$")
HOST_OK = re.compile(r"^([a-z0-9-]+\.)*(unicplaquiste\.com|netlify\.app)$")
IMG_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,80}\.(webp|jpg|jpeg|png)$")
IMG_BASE = "https://www.unicplaquiste.com/images/"
CTRL = re.compile(r"[\x00-\x1f\x7f<>]")
TYPES = ("title", "text", "photo", "gallery", "stats", "quote", "page", "outro")
MAX_SCENES, MAX_TOTAL = 14, 120.0


def _txt(v, n: int) -> str:
    return CTRL.sub("", str(v or "")).strip()[:n]


def _secs(v, lo: float, hi: float, dflt: float) -> float:
    try:
        return round(min(hi, max(lo, float(v))), 2)
    except (TypeError, ValueError):
        return dflt


def _img(v) -> str:
    n = str(v or "")
    if not IMG_RE.match(n) or ".." in n:
        raise ValueError(f"image refusée : {n[:30]}")
    return (os.environ.get("VIDEO_IMG_BASE") or IMG_BASE) + n


def _url(raw) -> str:
    u = urlparse(str(raw or ""))
    local = os.environ.get("VIDEO_ALLOW_LOCAL") == "1" and u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
    if not local and not (u.scheme == "https" and u.hostname and HOST_OK.match(u.hostname) and not u.username):
        raise ValueError("adresse refusée : seul unicplaquiste.com (ou un aperçu Netlify) est filmé")
    return str(raw)


def _scene(s: dict) -> dict:
    t = s.get("type")
    if t not in TYPES:
        raise ValueError(f"type de scène inconnu : {str(t)[:20]}")
    if t == "title":
        return {"type": t, "seconds": _secs(s.get("seconds"), 2.5, 8, 4), "l1": _txt(s.get("l1"), 24).upper(), "l2": _txt(s.get("l2"), 24).upper(), "sub": _txt(s.get("sub"), 40).upper()}
    if t == "text":
        b = [_txt(x, 70) for x in (s.get("bullets") or []) if _txt(x, 70)][:4]
        if not b:
            raise ValueError("scène texte sans contenu")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 10, 5), "heading": _txt(s.get("heading"), 40), "bullets": b}
    if t == "photo":
        return {"type": t, "seconds": _secs(s.get("seconds"), 2.5, 8, 4), "src": _img(s.get("image")), "caption": _txt(s.get("caption"), 60),
                "dir": s.get("direction") if s.get("direction") in ("in", "out", "left", "right") else "in"}
    if t == "gallery":
        imgs = [_img(x) for x in (s.get("images") or [])][:6]
        if len(imgs) < 2:
            raise ValueError("galerie : au moins 2 images")
        return {"type": t, "seconds": _secs(s.get("seconds"), 4, 14, 2.4 * len(imgs)), "srcs": imgs, "caption": _txt(s.get("caption"), 60)}
    if t == "stats":
        items = []
        for it in (s.get("items") or [])[:4]:
            try:
                v = int(it.get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            items.append({"value": min(max(v, 0), 100000), "suffix": CTRL.sub("", str(it.get("suffix") or ""))[:4], "label": _txt(it.get("label"), 28)})
        if len(items) < 2:
            raise ValueError("chiffres : au moins 2")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 9, 5), "items": items}
    if t == "quote":
        q = _txt(s.get("text"), 220)
        if not q:
            raise ValueError("citation vide")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 10, 6), "text": q, "author": _txt(s.get("author"), 40)}
    if t == "outro":
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 8, 5), "lines": [_txt(x, 60) for x in (s.get("lines") or [])][:6]}
    ch = []
    for c in (s.get("chapters") or [])[:8]:
        sel = str((c or {}).get("selector") or "")
        if not SEL_RE.match(sel):
            raise ValueError(f"sélecteur refusé : {sel[:30]}")
        ch.append({"selector": sel, "label": _txt(c.get("label"), 24) or "Suite", "seconds": _secs(c.get("seconds"), 2.5, 9, 4)})
    if not ch:
        raise ValueError("scène page sans chapitre")
    return {"type": t, "url": _url(s.get("url")), "hero_seconds": _secs(s.get("hero_seconds"), 2, 6, 4.4), "chapters": ch,
            "seconds": 0}   # durée réelle fixée par la capture


def clean(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("scénario invalide")
    if "scenes" not in raw:   # ancienne forme : titre + page + fin
        t = [_txt(x, 24) for x in (raw.get("title") or ["UNIC", "PLAQUISTE"])]
        raw = {"format": "vertical", "scenes": [{"type": "title", "l1": t[0], "l2": t[1] if len(t) > 1 else "", "sub": raw.get("subtitle", "")},
                                                 {"type": "page", "url": raw.get("url"), "hero_seconds": raw.get("hero_seconds"), "chapters": raw.get("chapters")},
                                                 {"type": "outro", "lines": raw.get("end")}]}
    fmt = raw.get("format") if raw.get("format") in FORMATS else "vertical"
    scenes = [_scene(s) for s in (raw.get("scenes") or [])[:MAX_SCENES] if isinstance(s, dict)]
    if not scenes:
        raise ValueError("aucune scène")
    est = sum(s["seconds"] or (s["hero_seconds"] + sum(c["seconds"] for c in s["chapters"]) + 2.5) for s in scenes)
    if est > MAX_TOTAL:
        raise ValueError("vidéo trop longue (120 s au maximum)")
    return {"format": fmt, "scenes": scenes}
