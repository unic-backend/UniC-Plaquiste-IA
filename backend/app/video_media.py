"""Médias du patron pour le Studio vidéo : ses films de chantier, sa musique, sa voix (ex. ElevenLabs).

Stockés sur le disque du serveur (`storage/video_media`). GitHub Actions, qui fabrique la vidéo, les télécharge par un lien secret
(`/api/public/video-media/<jeton>`) ouvert SEULEMENT après le clic « Lancer la fabrication », pendant OPEN_HOURS, et seulement pour
les médias de cette vidéo. Rien n'est publié. Pas de suppression physique (décision du propriétaire) : « retirer » cache le média.

Voix : les phrases sont repérées par les silences (ffmpeg silencedetect) ; si le patron colle son texte et que le nombre de phrases
correspond, chaque morceau reçoit sa phrase. L'IA du Studio place ensuite chaque phrase sur sa scène (clé `phrases`).
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

KEY = "video_media"
KINDS = {   # (taille maximale en Mo, extensions acceptées)
    "clip": (250, (".mp4", ".mov", ".m4v", ".webm")),
    "music": (40, (".mp3", ".m4a", ".aac", ".wav", ".ogg")),
    "voice": (40, (".mp3", ".m4a", ".aac", ".wav", ".ogg")),
}
KIND_FR = {"clip": "Vidéo", "music": "Musique", "voice": "Voix"}
MAX_LIBRARY_BYTES = 3 * 1024 ** 3      # garde-fou du disque (5 Go sur Render)
MAX_ITEMS = 300
OPEN_HOURS = 72                        # durée d'ouverture d'un lien après le lancement d'une fabrication
SILENCE_DB, SILENCE_S = -38, 0.28      # repérage des phrases d'une voix
ID_RE = re.compile(r"^[a-f0-9]{12}$")


class MediaError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _dir() -> Path:
    p = settings.storage_path / "video_media"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load(db: Session) -> list[dict]:
    if db is None or not hasattr(db, "get"):   # appels sans base (tests, scénario standard) : aucun média
        return []
    row = db.get(AppSetting, KEY)
    try:
        data = json.loads(row.value) if row and row.value else []
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _save(db: Session, items: list[dict]) -> None:
    value = json.dumps(items, ensure_ascii=False)
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    db.flush()


def probe_seconds(path: Path) -> float:
    """Durée d'un fichier audio/vidéo (ffprobe) ; 0 si illisible."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return round(float(out), 2)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def detect_phrases(path: Path, total: float) -> list[list[float]]:
    """Morceaux parlés d'une voix, séparés par les silences : [[début, fin], …] en secondes."""
    try:
        err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_S}",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=300).stderr
    except (OSError, subprocess.SubprocessError):
        return [[0.0, total]] if total else []
    return phrases_from_log(err, total)


def phrases_from_log(log: str, total: float) -> list[list[float]]:
    """Transforme le journal de silencedetect en morceaux parlés (fonction pure, testée)."""
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    out, cur = [], 0.0
    for i, s in enumerate(starts):
        if s - cur > 0.15:
            out.append([round(max(0.0, cur), 2), round(s, 2)])
        cur = ends[i] if i < len(ends) else total
    if total - cur > 0.15:
        out.append([round(cur, 2), round(total, 2)])
    return out


def split_script(text: str) -> list[str]:
    """Phrases d'un texte de voix off (coupure après . ! ? … et aux retours à la ligne)."""
    parts = re.split(r"(?<=[.!?…])\s+|\n+", str(text or ""))
    return [" ".join(p.split())[:200] for p in parts if p and p.strip()]


def _public(it: dict) -> dict:
    out = {k: it[k] for k in ("id", "kind", "name", "seconds", "size", "at") if k in it}
    if it["kind"] == "voice":
        texts = it.get("texts") or []
        out["phrases"] = [{"i": i, "start": a, "end": b, "text": texts[i] if i < len(texts) else None} for i, (a, b) in enumerate(it.get("phrases") or [])]
    return out


def listing(db: Session) -> list[dict]:
    return [_public(it) for it in _load(db) if not it.get("hidden")]


def items_by_id(db: Session) -> dict[str, dict]:
    """Médias visibles, par identifiant (pour construire un scénario)."""
    return {it["id"]: it for it in _load(db) if not it.get("hidden")}


async def add(db: Session, upload, kind: str, script: str = "") -> dict:
    """Enregistre un média envoyé par le patron (lu par morceaux, jamais entier en mémoire)."""
    if kind not in KINDS:
        raise MediaError("Type de média inconnu (vidéo, musique ou voix).")
    max_mb, exts = KINDS[kind]
    name = Path(str(getattr(upload, "filename", "") or "media")).name[:120]
    ext = Path(name).suffix.lower()
    if ext not in exts:
        raise MediaError(f"{KIND_FR[kind]} : formats acceptés {', '.join(exts)}.")
    items = _load(db)
    if len(items) >= MAX_ITEMS:
        raise MediaError("Trop de médias enregistrés : retire ceux qui ne servent plus.", 409)
    used = sum(int(it.get("size") or 0) for it in items if not it.get("hidden"))
    limit = max_mb * 1024 * 1024
    mid = uuid.uuid4().hex[:12]
    dest = _dir() / f"{mid}{ext}"
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit or used + size > MAX_LIBRARY_BYTES:
                f.close()
                dest.unlink(missing_ok=True)   # envoi refusé : fichier incomplet, jamais enregistré
                raise MediaError(f"{KIND_FR[kind]} trop volumineuse ({max_mb} Mo maximum)." if size > limit
                                 else "Espace des médias plein (3 Go) : retire des médias avant d'en ajouter.", 413)
            f.write(chunk)
    secs = probe_seconds(dest)
    if secs <= 0:
        dest.unlink(missing_ok=True)           # fichier illisible : jamais enregistré
        raise MediaError("Fichier illisible : envoie une vraie vidéo ou un vrai fichier audio.")
    it = {"id": mid, "kind": kind, "name": name, "ext": ext, "size": size, "seconds": secs, "at": int(time.time()),
          "token": secrets.token_urlsafe(24), "open_until": 0}
    if kind == "voice":
        it["phrases"] = detect_phrases(dest, secs)
        lines = split_script(script)
        it["texts"] = lines if len(lines) == len(it["phrases"]) else []
        it["script"] = " ".join(lines)[:6000]
    items.append(it)
    _save(db, items)
    return _public(it)


def hide(db: Session, mid: str) -> None:
    """« Retirer » : le média disparaît de la liste et des scénarios (le fichier reste sur le disque)."""
    items = _load(db)
    for it in items:
        if it["id"] == mid:
            it["hidden"] = True
            it["open_until"] = 0
            _save(db, items)
            return
    raise MediaError("Média introuvable.", 404)


def catalog_text(db: Session) -> str:
    """Ce que l'IA du Studio peut utiliser (identifiants exacts), ou "" s'il n'y a rien."""
    items = items_by_id(db)
    if not items:
        return ""
    lines = []
    for it in items.values():
        if it["kind"] == "clip":
            lines.append(f"- vidéo {it['id']} : « {it['name']} », {it['seconds']:.1f} s")
        elif it["kind"] == "music":
            lines.append(f"- musique {it['id']} : « {it['name']} », {it['seconds']:.0f} s")
        else:
            ph = it.get("phrases") or []
            texts = it.get("texts") or []
            desc = "; ".join(f"#{i} ({b - a:.1f} s){' « ' + texts[i] + ' »' if texts else ''}" for i, (a, b) in enumerate(ph))
            extra = "" if texts else (f" Texte complet (dans l'ordre) : « {it.get('script')} »" if it.get("script") else "")
            lines.append(f"- voix {it['id']} : {len(ph)} phrases : {desc}.{extra}")
    return "\n".join(lines)


def public_path(db: Session, token: str) -> Path | None:
    """Fichier d'un lien secret, seulement s'il est ouvert (fabrication lancée) et pas retiré."""
    if not token or len(token) > 64:
        return None
    now = time.time()
    for it in _load(db):
        if not it.get("hidden") and secrets.compare_digest(str(it.get("token") or ""), token) and float(it.get("open_until") or 0) > now:
            p = _dir() / f"{it['id']}{it['ext']}"
            return p if p.exists() else None
    return None


def media_type(path: Path) -> str:
    return {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".aac": "audio/aac", ".wav": "audio/wav", ".ogg": "audio/ogg"}.get(path.suffix.lower(), "application/octet-stream")


def _base_url() -> str:
    base = (settings.unic_public_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise MediaError("Tes médias doivent être téléchargés par GitHub : indique l'adresse https du serveur (réglage UNIC_PUBLIC_URL).", 400)
    return base


def to_engine(db: Session, spec: dict) -> dict:
    """Scénario du Studio -> forme du moteur : « my_clip » devient un clip avec lien secret, « phrases » un morceau de voix,
    « audio » la bande son. Les liens des médias utilisés s'ouvrent pour OPEN_HOURS (clic « Lancer » du patron en amont)."""
    if not any(s.get("type") == "my_clip" or s.get("phrases") for s in spec.get("scenes") or []) and not spec.get("audio"):
        return spec
    items = _load(db)
    by_id = {it["id"]: it for it in items if not it.get("hidden")}
    base, used = _base_url(), set()

    def link(mid: str, kind: str) -> str:
        it = by_id.get(mid)
        if not it or it["kind"] != kind:
            raise MediaError(f"{KIND_FR[kind]} {mid} introuvable : elle a été retirée ? Propose à nouveau le scénario.", 409)
        used.add(mid)
        return f"{base}/api/public/video-media/{it['token']}"

    au = spec.get("audio") or {}
    voice = by_id.get(au.get("voice") or "")
    scenes = []
    for s in spec.get("scenes") or []:
        s = dict(s)
        ph = s.pop("phrases", None)
        if s.get("type") == "my_clip":
            s = {"type": "clip", "url": link(s["media"], "clip"), "seconds": s["seconds"], "start": s.get("start", 0),
                 **({"overlay": s["overlay"]} if s.get("overlay") else {})}
        if ph and voice and voice.get("phrases"):
            i, j = ph
            s["voice"], s["voice_at"] = [voice["phrases"][i][0], voice["phrases"][j][1]], 0.25
        scenes.append(s)
    out = {k: v for k, v in spec.items() if k not in ("scenes", "audio")}
    out["scenes"] = scenes
    if au:
        eng = {"keys": bool(au.get("keys", True)), "duck": au.get("duck") or "normal"}
        if au.get("music"):
            eng["music"] = {"url": link(au["music"], "music"), "start": au.get("music_start", 0), "volume": 1}
        if au.get("voice"):
            eng["voice"] = {"url": link(au["voice"], "voice"), "offset": 0, "volume": 1}
        out["audio"] = eng
    until = time.time() + OPEN_HOURS * 3600
    for it in items:
        if it["id"] in used:
            it["open_until"] = until
    _save(db, items)
    return out
