"""Médias du patron pour le Studio vidéo : ses films de chantier, sa musique, sa voix (ex. ElevenLabs).

Stockés sur le disque du serveur (`storage/video_media`). GitHub Actions, qui fabrique la vidéo, les télécharge par un lien secret
(`/api/public/video-media/<jeton>`) ouvert SEULEMENT après le clic « Lancer la fabrication », pendant OPEN_HOURS, et seulement pour
les médias de cette vidéo. Rien n'est publié. Pas de suppression physique (décision du propriétaire) : « retirer » cache le média.

Vidéos : l'IA les REGARDE (vision.describe_frames) — LOOK_FRAMES images extraites puis décrites une fois pour toutes ; le scénariste
reçoit « ce qu'on voit à tel instant » et choisit ses passages d'après ça, au lieu d'un simple nom de fichier.

Voix : les phrases sont repérées par les silences (ffmpeg silencedetect) ; si le patron colle son texte et que le nombre de phrases
correspond, chaque morceau reçoit sa phrase. L'IA du Studio place ensuite chaque phrase sur sa scène (clé `phrases`).
"""
from __future__ import annotations

import asyncio
import json
import math
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
LOOK_FRAMES = 8                        # images regardées par vidéo (un seul appel vision : coût borné)
LOOK_MAX_PER_CALL = 6                  # vidéos regardées au plus avant un scénario (délai borné)
LOOK_RETRY_S = 600                     # vision échouée : on réessaie au plus toutes les 10 minutes
FRAME_SIDE = 512                       # taille des images extraites (côté le plus long, en pixels)


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


def frame_times(seconds: float, n: int = LOOK_FRAMES) -> list[float]:
    """Instants regardés dans une vidéo : n images réparties au milieu de n parts égales (jamais la toute première ni la dernière image)."""
    if seconds <= 0:
        return []
    n = max(1, min(n, int(seconds * 2) or 1))     # vidéo très courte : moins d'images
    return [round((i + 0.5) * seconds / n, 1) for i in range(n)]


def grab_frame(src: Path, t: float, dest: Path, side: int = FRAME_SIDE) -> bool:
    """Une image JPEG de la vidéo à l'instant t (petite : sert à regarder et aux vignettes)."""
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale='min({side},iw)':-2", "-q:v", "4", str(dest)], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return dest.exists() and dest.stat().st_size > 0


def _frame_file(mid: str, t: float) -> Path:
    p = _dir() / "frames"
    p.mkdir(exist_ok=True)
    return p / f"{mid}-{int(round(t * 10))}.jpg"


LOOK_LINE = re.compile(r"^\W*#?\s*(\d{1,3})\s*[:.)–—-]\s*(.+)$")
SUMMARY_LINE = re.compile(r"^\W*r[ée]sum[ée]\s*:\s*(.+)$", re.I)


def parse_looks(text: str, times: list[float]) -> tuple[list[list], str]:
    """Réponse de la vision -> ([[instant, ce qu'on voit], …], résumé). Fonction pure, testée ; textes nettoyés et bornés (ce sont des données)."""
    def clean(s: str, n: int) -> str:
        return " ".join(re.sub(r"[\x00-\x1f\x7f<>]", " ", s).split()).strip(" *_")[:n]
    looks, summary, seen = [], "", set()
    for line in str(text or "").splitlines():
        m = SUMMARY_LINE.match(line.strip())
        if m:
            summary = clean(m.group(1), 240)
            continue
        m = LOOK_LINE.match(line.strip())
        if m and int(m.group(1)) < len(times) and int(m.group(1)) not in seen and clean(m.group(2), 160):
            seen.add(int(m.group(1)))
            looks.append([times[int(m.group(1))], clean(m.group(2), 160)])
    return sorted(looks), summary


def _frames(src: Path, mid: str, seconds: float) -> list[tuple[float, Path]]:
    """Images à regarder (gardées en cache). Une seule extraction ffmpeg à la fois : le serveur n'a que 512 Mo."""
    out = []
    for t in frame_times(seconds):
        f = _frame_file(mid, t)
        if f.exists() or grab_frame(src, t, f):
            out.append((t, f))
    return out


def _describe(frames: list[tuple[float, Path]]) -> dict | None:
    from app import vision
    if not frames:
        return None
    looks, summary = parse_looks(vision.describe_frames(frames), [t for t, _ in frames])
    return {"looks": looks, "summary": summary} if looks else None


def look(src: Path, mid: str, seconds: float) -> dict | None:
    """L'IA REGARDE la vidéo : images extraites puis décrites (vision Claude). None si impossible (pas de clé, échec) : on réessaiera."""
    from app import vision
    if not vision.disponible():
        return None
    return _describe(_frames(src, mid, seconds))


def ensure_looks(db: Session, limit: int = LOOK_MAX_PER_CALL) -> int:
    """Avant d'écrire un scénario : regarde les vidéos jamais regardées (envoyées avant cette fonction, ou dont la vision a échoué),
    au plus `limit`. Le résultat est gardé : chaque vidéo n'est regardée qu'une fois. Rend le nombre regardé."""
    from app import vision
    if not vision.disponible():
        return 0
    items, now = _load(db), time.time()
    todo = [it for it in items if it.get("kind") == "clip" and not it.get("hidden") and "looks" not in it
            and now - float(it.get("look_try") or 0) > LOOK_RETRY_S and (_dir() / f"{it['id']}{it['ext']}").exists()][:limit]
    if not todo:
        return 0
    frames = [_frames(_dir() / f"{it['id']}{it['ext']}", it["id"], float(it["seconds"])) for it in todo]   # une vidéo après l'autre (mémoire)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(todo)) as pool:      # appels vision en parallèle (réseau) ; la base reste dans ce fil
        got = list(pool.map(_describe, frames))
    for it, g in zip(todo, got):
        if g:
            it.update(g)
            it.pop("look_try", None)
        else:
            it["look_try"] = int(now)
    _save(db, items)
    if hasattr(db, "commit"):
        db.commit()      # gardé même si le scénario échoue ensuite : la vidéo n'est pas regardée (et payée) deux fois
    return sum(1 for g in got if g)


def frame_path(db: Session, mid: str, t: float) -> Path | None:
    """Vignette d'un passage (fichier en cache, arrondi à la demi-seconde) ; None si la vidéo n'existe pas ou est retirée."""
    it = items_by_id(db).get(mid)
    if not it or it["kind"] != "clip" or not math.isfinite(float(t)):
        return None
    t = round(min(max(0.0, float(t)), max(0.0, float(it["seconds"]) - 0.2)) * 2) / 2
    f = _frame_file(mid, t)
    if f.exists() or grab_frame(_dir() / f"{mid}{it['ext']}", t, f):
        return f
    return None


def _public(it: dict) -> dict:
    out = {k: it[k] for k in ("id", "kind", "name", "seconds", "size", "at", "summary") if k in it}
    if it["kind"] == "clip":
        out["looks"] = [{"t": t, "text": x} for t, x in it.get("looks") or []]
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
    if kind == "clip":      # l'IA regarde la vidéo dès l'envoi (hors de la boucle du serveur) ; en cas d'échec, avant le prochain scénario
        from app import vision
        if vision.disponible():
            got = await asyncio.to_thread(look, dest, mid, secs)
            if got:
                it.update(got)
            else:
                it["look_try"] = int(time.time())
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
            seen = " | ".join(f"{t:.1f} s : {x}" for t, x in it.get("looks") or [])
            lines.append(f"- vidéo {it['id']} : « {it['name']} », {it['seconds']:.1f} s."
                         + (f" Résumé : {it['summary']}." if it.get("summary") else "")
                         + (f" Ce qu'on voit (instant : image) : {seen}" if seen else " (pas encore regardée : contenu inconnu)"))
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
