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
    "lottie": (3, (".json",)),                 # animation vectorielle (LottieFiles…), jouée par le moteur
    "photo": (25, (".jpg", ".jpeg", ".png", ".webp")),   # photo du patron (ré-enregistrée en JPEG, sans données de position)
}
KIND_FR = {"clip": "Vidéo", "music": "Musique", "voice": "Voix", "lottie": "Animation", "photo": "Photo"}
PHOTO_SIDE = 2560                      # photo gardée à 2560 px au plus (bien assez pour du 1080×1920)
VOICE_NAME = re.compile(r"voi[xc]|voice|eleven|narrat|speech|parole|commentaire", re.I)
MUSIC_NAME = re.compile(r"musi|song|chanson|instru|remix|official|\bfeat\b|\bbeat\b", re.I)
MAX_LIBRARY_BYTES = 3 * 1024 ** 3      # garde-fou du disque (5 Go sur Render)
MAX_ITEMS = 300
OPEN_HOURS = 72                        # durée d'ouverture d'un lien après le lancement d'une fabrication
SILENCE_DB, SILENCE_S = -38, 0.28      # repérage des phrases d'une voix
ID_RE = re.compile(r"^[a-f0-9]{12}$")
LOOK_FRAMES = 8                        # images regardées par vidéo (un seul appel vision : coût borné)
LOOK_MAX_PER_CALL = 6                  # vidéos regardées au plus avant un scénario (délai borné)
LOOK_RETRY_S = 600                     # vision échouée : on réessaie au plus toutes les 10 minutes
FRAME_SIDE = 512                       # taille des images extraites (côté le plus long, en pixels)
TALK_PAD, TALK_GAP, TALK_MIN = 0.12, 0.30, 0.5   # coupe des silences : marge autour des mots, pause gardée, plan le plus court (s)
TALK_SILENCE_S = 0.35                  # un silence plus long que ça est coupé
MAX_CUTS = 200                         # plans au plus par coupe des silences


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


def guess_kind(name: str) -> str | None:
    """Type d'un fichier d'après son extension (dépôt « tout ici ») : clip, photo, lottie, ou « audio » (musique ou voix : décidé à l'écoute)."""
    ext = Path(name).suffix.lower()
    for k in ("clip", "photo", "lottie"):
        if ext in KINDS[k][1]:
            return k
    return "audio" if ext in KINDS["music"][1] else None


def classify_audio(path: Path, secs: float, name: str) -> str:
    """Musique ou voix off ? Le nom d'abord (« voix », « ElevenLabs »…), sinon l'écoute : une voix fait des pauses entre ses phrases,
    une musique joue sans interruption. Le patron peut corriger d'un appui (set_kind)."""
    if VOICE_NAME.search(name):
        return "voice"
    if MUSIC_NAME.search(name):
        return "music"
    ph = detect_phrases(path, secs)
    spoken = sum(b - a for a, b in ph)
    return "voice" if len(ph) >= 3 and secs > 0 and (secs - spoken) / secs >= 0.08 else "music"


def _photo(src: Path, mid: str) -> tuple[Path, int, int]:
    """Photo ré-enregistrée en JPEG : tournée à l'endroit, 2560 px au plus, SANS les données EXIF (position GPS du téléphone)."""
    from PIL import Image, ImageOps
    with Image.open(src) as img:
        img.draft("RGB", (PHOTO_SIDE, PHOTO_SIDE))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
        dest = _dir() / f"{mid}.jpg"
        img.save(dest, "JPEG", quality=90, optimize=True)
        return dest, img.width, img.height


def lottie_seconds(path: Path) -> float:
    """Durée d'une animation Lottie, si c'en est une vraie et sûre (aucune ressource externe, structure valide) ; 0 sinon."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        fr, ip, op = float(d["fr"]), float(d["ip"]), float(d["op"])
        w, h = float(d["w"]), float(d["h"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0.0
    if not (isinstance(d.get("layers"), list) and d["layers"] and len(d["layers"]) <= 500 and 1 <= fr <= 120 and 0 < op - ip <= fr * 120 and 0 < w <= 8000 and 0 < h <= 8000):
        return 0.0
    return round((op - ip) / fr, 2)


def probe_seconds(path: Path) -> float:
    """Durée d'un fichier audio/vidéo (ffprobe) ; 0 si illisible."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return round(float(out), 2)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def detect_phrases(path: Path, total: float, noise: float = SILENCE_DB, gap: float = SILENCE_S) -> list[list[float]]:
    """Morceaux parlés d'une voix, séparés par les silences : [[début, fin], …] en secondes."""
    try:
        err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", f"silencedetect=noise={noise:g}dB:d={gap:g}",
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


def has_audio(path: Path) -> bool:
    """Le film a-t-il une piste son ?"""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


def mean_volume(path: Path) -> float | None:
    """Niveau moyen du son (dB) : sert à régler le seuil de silence d'un film (chantier bruyant ou pièce calme)."""
    try:
        err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=300).stderr
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m.group(1)) if m else None


def merge_talk(parts: list[list[float]], total: float, pad: float = TALK_PAD, gap: float = TALK_GAP, shortest: float = TALK_MIN) -> list[list[float]]:
    """Passages parlés -> plans à garder pour une coupe des silences : un peu de marge (aucun mot coupé), passages très proches
    réunis, bribes trop courtes écartées. Fonction pure, testée."""
    out: list[list[float]] = []
    for a, b in parts:
        a, b = max(0.0, a - pad), min(total, b + pad)
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 1), round(b, 1)] for a, b in out if b - a >= shortest]


def detect_talk(path: Path, total: float) -> list[list[float]]:
    """Passages où l'on entend quelqu'un parler (ou un son fort) dans un film : le reste est du silence à couper."""
    mv = mean_volume(path)
    noise = SILENCE_DB if mv is None else min(-25.0, max(-50.0, mv - 14))
    return merge_talk(detect_phrases(path, total, noise, TALK_SILENCE_S), total)


BEAT_SR, BEAT_HOP = 11025, 256         # rythme : son ramené à 11 kHz, une mesure d'énergie toutes les 23 ms
BEAT_BPM = (70.0, 180.0)               # tempos cherchés (au-delà : moitié ou double)
MAX_BEATS = 2000


def onset_envelope(path: Path, max_seconds: float = 600) -> tuple[list[float], float]:
    """Attaques du son (hausses d'énergie), image par image : ce que l'oreille entend comme des coups. Bibliothèque standard + ffmpeg."""
    import array
    try:
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-t", f"{max_seconds:g}", "-i", str(path), "-vn", "-ac", "1", "-ar", str(BEAT_SR), "-f", "s16le", "-"],
                             capture_output=True, timeout=300).stdout
    except (OSError, subprocess.SubprocessError):
        return [], 0.0
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    energy = []
    for i in range(0, len(a) - BEAT_HOP, BEAT_HOP):
        e = 0
        for v in a[i:i + BEAT_HOP]:
            e += v * v
        energy.append(math.log1p(e / BEAT_HOP))
    onsets = [0.0] + [max(0.0, energy[i] - energy[i - 1]) for i in range(1, len(energy))]
    for i in range(min(5, len(onsets))):    # le tout début du fichier (silence -> son) n'est pas un temps fort
        onsets[i] = 0.0
    return onsets, BEAT_SR / BEAT_HOP


def beats_from_onsets(env: list[float], fps: float) -> tuple[float, list[float]]:
    """Tempo (BPM) et temps forts (s) à partir des attaques. Fonction pure, testée.
    1. Tempo : autocorrélation des attaques (préférence douce autour de 120 BPM contre les erreurs de double/moitié), affinée entre
       deux images. 2. Temps forts : programmation dynamique (méthode d'Ellis, celle de librosa) — chaque temps tombe sur une attaque
       ET garde un écart régulier, au lieu de dériver."""
    n = len(env)
    if n < fps * 4:
        return 0.0, []
    mean = sum(env) / n
    x = [v - mean for v in env]
    sd = math.sqrt(sum(v * v for v in x) / n)
    if sd <= 0:
        return 0.0, []
    lo_l, hi_l = max(2, int(fps * 60 / BEAT_BPM[1])), int(fps * 60 / BEAT_BPM[0]) + 1
    ac = {L: sum(x[i] * x[i + L] for i in range(n - L)) / (n - L) for L in range(lo_l - 1, hi_l + 2)}
    score = {L: ac[L] * math.exp(-0.5 * (math.log2(60 * fps / L / 120)) ** 2) for L in range(lo_l, hi_l + 1)}
    L = max(score, key=score.get)
    a, b, c = ac[L - 1], ac[L], ac[L + 1]
    den = a - 2 * b + c
    period = L + (0.5 * (a - c) / den if den < 0 else 0.0)        # sommet entre deux images
    o = [v / sd for v in env]
    total, back = [0.0] * n, [-1] * n
    for t in range(n):
        best, bi = 0.0, -1
        for prev in range(max(0, t - int(round(2 * period))), t - int(round(period / 2)) + 1):
            v = total[prev] - 100.0 * math.log((t - prev) / period) ** 2
            if v > best:
                best, bi = v, prev
        total[t], back[t] = o[t] + best, bi
    tail = range(max(0, n - int(round(period))), n)
    k = max(tail, key=lambda i: total[i])
    frames = []
    while k >= 0 and len(frames) < MAX_BEATS:
        frames.append(k)
        k = back[k]
    frames.reverse()
    if len(frames) < 3:
        return 0.0, []
    gaps = sorted(q - p for p, q in zip(frames, frames[1:]))
    return round(60 * fps / ((frames[-1] - frames[0]) / (len(frames) - 1) if gaps else period), 1), [round(f / fps, 2) for f in frames]


def detect_beats(path: Path) -> tuple[float, list[float]]:
    env, fps = onset_envelope(path)
    return beats_from_onsets(env, fps) if fps else (0.0, [])


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


def look(src: Path, mid: str, seconds: float, kind: str = "clip") -> dict | None:
    """L'IA REGARDE la vidéo (images extraites) ou la photo, puis la décrit (vision Claude). None si impossible (pas de clé, échec) : on réessaiera."""
    from app import vision
    if not vision.disponible():
        return None
    return _describe([(0.0, src)] if kind == "photo" else _frames(src, mid, seconds))


def ensure_looks(db: Session, limit: int = LOOK_MAX_PER_CALL) -> int:
    """Avant d'écrire un scénario : regarde les vidéos jamais regardées (envoyées avant cette fonction, ou dont la vision a échoué),
    au plus `limit`. Le résultat est gardé : chaque vidéo n'est regardée qu'une fois. Rend le nombre regardé."""
    from app import vision
    if not vision.disponible():
        return 0
    items, now = _load(db), time.time()
    todo = [it for it in items if it.get("kind") in ("clip", "photo") and not it.get("hidden") and "looks" not in it
            and now - float(it.get("look_try") or 0) > LOOK_RETRY_S and (_dir() / f"{it['id']}{it['ext']}").exists()][:limit]
    if not todo:
        return 0
    frames = [[(0.0, _dir() / f"{it['id']}{it['ext']}")] if it["kind"] == "photo" else _frames(_dir() / f"{it['id']}{it['ext']}", it["id"], float(it["seconds"]))
              for it in todo]   # une vidéo après l'autre (mémoire)
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


def set_kind(db: Session, mid: str, kind: str) -> dict:
    """Le patron corrige le type d'un son d'un appui : musique <-> voix off (rythme ou phrases recalculés)."""
    if kind not in ("music", "voice"):
        raise MediaError("Seul un son peut passer de musique à voix off (et inversement).")
    items = _load(db)
    it = next((x for x in items if x["id"] == mid and not x.get("hidden")), None)
    if not it or it["kind"] not in ("music", "voice"):
        raise MediaError("Son introuvable.", 404)
    if it["kind"] != kind:
        src = _dir() / f"{it['id']}{it['ext']}"
        it["kind"] = kind
        if kind == "voice":
            it["phrases"], it["texts"], it["script"] = detect_phrases(src, float(it["seconds"])), [], ""
        else:
            it["bpm"], it["beats"] = detect_beats(src)
        _save(db, items)
    return _public(it)


def ensure_beats(db: Session) -> int:
    """Musiques envoyées avant le repérage du rythme : temps forts calculés maintenant (une fois)."""
    items, done = _load(db), 0
    for it in items:
        src = _dir() / f"{it['id']}{it.get('ext', '')}"
        if it.get("kind") == "music" and not it.get("hidden") and "beats" not in it and src.exists():
            it["bpm"], it["beats"] = detect_beats(src)
            done += 1
    if done:
        _save(db, items)
        if hasattr(db, "commit"):
            db.commit()
    return done


def ensure_sound(db: Session) -> int:
    """Films envoyés avant le repérage du son : piste son et passages parlés calculés maintenant (une seule fois, un film après l'autre)."""
    items, done = _load(db), 0
    for it in items:
        src = _dir() / f"{it['id']}{it.get('ext', '')}"
        if it.get("kind") == "clip" and not it.get("hidden") and "audio" not in it and src.exists():
            it["audio"] = has_audio(src)
            it["talk"] = detect_talk(src, float(it["seconds"])) if it["audio"] else []
            done += 1
    if done:
        _save(db, items)
        if hasattr(db, "commit"):
            db.commit()
    return done


MAX_WORDS_SECONDS = 1800               # transcription : 30 minutes de son au plus par média (crédit ElevenLabs)


def transcribe(db: Session, mid: str) -> dict:
    """Clic du patron « Sous-titres » : les mots dits dans sa vidéo ou sa voix off, avec leurs instants (ElevenLabs).
    Seul le son part chez ElevenLabs (mono, compressé), jamais l'image. Gardé : un média n'est transcrit qu'une fois."""
    from app import voice
    items = _load(db)
    it = next((x for x in items if x["id"] == mid and not x.get("hidden")), None)
    if not it or it["kind"] not in ("clip", "voice"):
        raise MediaError("Média introuvable.", 404)
    if it["kind"] == "clip" and it.get("audio") is False:
        raise MediaError("Cette vidéo n'a pas de son : rien à sous-titrer.")
    if float(it["seconds"]) > MAX_WORDS_SECONDS:
        raise MediaError("Son trop long pour les sous-titres (30 minutes au maximum).", 413)
    got = _words_of(it, voice.api_key(db))
    it["words"], it["lang"] = got["words"], got["language"]
    it.pop("words_try", None)
    _save(db, items)
    return _public(it)


def _words_of(it: dict, key: str) -> dict:
    """Son du média (mono, compressé) -> mots datés par ElevenLabs. Sans base de données : utilisable hors du fil du serveur."""
    from app import voice
    src = _dir() / f"{it['id']}{it['ext']}"
    try:
        audio = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", "-f", "mp3", "-"],
                               capture_output=True, timeout=600).stdout
    except (OSError, subprocess.SubprocessError):
        audio = b""
    if not audio:
        raise MediaError("Son illisible : impossible de préparer la transcription.")
    try:
        got = voice.transcribe(None, audio, f"{it['id']}.mp3", key=key)
    except voice.VoiceError as exc:
        raise MediaError(str(exc), exc.status)
    if not got["words"]:
        raise MediaError("Aucun mot reconnu dans ce son.", 422)
    return got


AUTO_KEY = "video_auto_words"
AUTO_MAX_SECONDS = 600                 # sous-titres automatiques : 10 minutes de son au plus par média (au-delà : bouton)
AUTO_PER_PLAN = 3                      # médias transcrits au plus avant un scénario
SPEAKING = re.compile(r"\bparl|face (à la )?cam|interview|explique|s'adresse|discours|présente", re.I)


def auto_words(db: Session) -> bool:
    """Sous-titres automatiques (réglage du patron, activé par défaut) : crédit ElevenLabs consommé sans clic."""
    if db is None or not hasattr(db, "get"):
        return False
    row = db.get(AppSetting, AUTO_KEY)
    return not (row and row.value == "0")


def set_auto_words(db: Session, on: bool) -> bool:
    row = db.get(AppSetting, AUTO_KEY)
    if row is None:
        db.add(AppSetting(key=AUTO_KEY, value="1" if on else "0"))
    else:
        row.value = "1" if on else "0"
    db.flush()
    return on


def wants_words(it: dict) -> bool:
    """Ce média mérite des sous-titres automatiques : une voix off, ou un film où quelqu'un PARLE (pauses entre des passages sonores,
    ou l'IA a vu une personne qui parle) — jamais un film de chantier au bruit continu (crédit gaspillé)."""
    if it.get("hidden") or it.get("words") or float(it.get("seconds") or 0) > AUTO_MAX_SECONDS:
        return False
    if it.get("kind") == "voice":
        return True
    return it.get("kind") == "clip" and bool(it.get("audio")) and (len(it.get("talk") or []) >= 2 or bool(SPEAKING.search(str(it.get("summary") or ""))))


def ensure_words(db: Session, limit: int = AUTO_PER_PLAN) -> int:
    """Avant un scénario (réglage activé) : sous-titres des médias parlés qui n'en ont pas encore. Un échec n'arrête rien (réessai 10 min plus tard)."""
    from app import voice
    if not auto_words(db):
        return 0
    key = voice.api_key(db)
    if not key:
        return 0
    items, now, done = _load(db), time.time(), 0
    todo = [it for it in items if wants_words(it) and now - float(it.get("words_try") or 0) > LOOK_RETRY_S][:limit]
    for it in todo:
        try:
            got = _words_of(it, key)
            it["words"], it["lang"] = got["words"], got["language"]
            it.pop("words_try", None)
            done += 1
        except MediaError:
            it["words_try"] = int(now)
    if todo:
        _save(db, items)
        if hasattr(db, "commit"):
            db.commit()
    return done


def scene_words(words: list, a: float, b: float, offset: float = 0.0) -> list[list]:
    """Mots dits entre a et b (instants du fichier) -> instants dans la scène (offset : où commence le son dans la scène). Pure, testée."""
    return [[round(w0 - a + offset, 2), round(w1 - a + offset, 2), txt] for w0, w1, txt in words or [] if w0 >= a - 0.05 and w0 < b]


def frame_path(db: Session, mid: str, t: float) -> Path | None:
    """Vignette d'un passage de vidéo (fichier en cache, arrondi à la demi-seconde) ou d'une photo ; None si le média n'existe pas ou est retiré."""
    it = items_by_id(db).get(mid)
    if it and it["kind"] == "photo":
        f = _frame_file(mid, -1)
        if not f.exists():
            try:
                from PIL import Image
                with Image.open(_dir() / f"{mid}{it['ext']}") as img:
                    img.thumbnail((FRAME_SIDE, FRAME_SIDE))
                    img.convert("RGB").save(f, "JPEG", quality=82)
            except Exception:      # noqa: BLE001
                return None
        return f
    if not it or it["kind"] != "clip" or not math.isfinite(float(t)):
        return None
    t = round(min(max(0.0, float(t)), max(0.0, float(it["seconds"]) - 0.2)) * 2) / 2
    f = _frame_file(mid, t)
    if f.exists() or grab_frame(_dir() / f"{mid}{it['ext']}", t, f):
        return f
    return None


def _public(it: dict) -> dict:
    out = {k: it[k] for k in ("id", "kind", "name", "seconds", "size", "at", "summary", "bpm", "dims") if k in it}
    if it.get("words"):
        out["words"] = len(it["words"])
    if it["kind"] == "clip":
        out["looks"] = [{"t": t, "text": x} for t, x in it.get("looks") or []]
        if "audio" in it:
            out["audio"], out["talk"] = bool(it["audio"]), len(it.get("talk") or [])
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
    name = Path(str(getattr(upload, "filename", "") or "media")).name[:120]
    ext = Path(name).suffix.lower()
    auto_audio = False
    if kind == "auto":         # « dépose tout ici » : le type vient du fichier
        g = guess_kind(name)
        if not g:
            raise MediaError(f"{name} : format non reconnu. Vidéo (.mp4, .mov), photo (.jpg, .png), son (.mp3, .m4a, .wav) ou animation Lottie (.json).")
        auto_audio, kind = g == "audio", "music" if g == "audio" else g
    if kind not in KINDS:
        raise MediaError("Type de média inconnu (vidéo, photo, musique, voix ou animation).")
    max_mb, exts = KINDS[kind]
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
    dims = None
    if kind == "photo":
        try:
            photo, w, h = _photo(dest, mid)
        except Exception:      # noqa: BLE001 — format illisible (HEIC…), image corrompue
            dest.unlink(missing_ok=True)       # envoi refusé : jamais enregistré
            raise MediaError(f"{name} : photo illisible. Sur le téléphone, choisis le format JPEG (pas HEIC).")
        if photo != dest:
            dest.unlink(missing_ok=True)       # l'original (PNG, WEBP, avec EXIF) est remplacé par la copie propre
        dest, ext, size, dims = photo, ".jpg", photo.stat().st_size, [w, h]
    secs = 0.0 if kind == "photo" else lottie_seconds(dest) if kind == "lottie" else probe_seconds(dest)
    if auto_audio and secs > 0:
        kind = classify_audio(dest, secs, name)
    if secs <= 0 and kind != "photo":
        dest.unlink(missing_ok=True)           # fichier illisible : jamais enregistré
        raise MediaError("Animation illisible : envoie un fichier Lottie (.json) de LottieFiles." if kind == "lottie"
                         else "Fichier illisible : envoie une vraie vidéo ou un vrai fichier audio.")
    it = {"id": mid, "kind": kind, "name": name, "ext": ext, "size": size, "seconds": secs, "at": int(time.time()),
          "token": secrets.token_urlsafe(24), "open_until": 0, **({"dims": dims} if dims else {})}
    if kind == "music":      # rythme : les coupes du montage tombent sur les temps forts
        it["bpm"], it["beats"] = detect_beats(dest)
    if kind == "voice":
        it["phrases"] = detect_phrases(dest, secs)
        lines = split_script(script)
        it["texts"] = lines if len(lines) == len(it["phrases"]) else []
        it["script"] = " ".join(lines)[:6000]
    if kind == "clip":      # son du film : parole repérée pour garder la voix et couper les silences
        it["audio"] = has_audio(dest)
        it["talk"] = detect_talk(dest, secs) if it["audio"] else []
    if kind in ("clip", "photo"):      # l'IA regarde la vidéo ou la photo dès l'envoi (hors de la boucle du serveur) ; en cas d'échec, avant le prochain scénario
        from app import vision
        if vision.disponible():
            got = await asyncio.to_thread(look, dest, mid, secs, kind)
            if got:
                it.update(got)
            else:
                it["look_try"] = int(time.time())
    if kind in ("clip", "voice") and auto_words(db) and wants_words(it):   # sous-titres automatiques (réglage du patron) : hors de la boucle du serveur
        from app import voice
        key = voice.api_key(db)
        if key:
            try:
                got = await asyncio.to_thread(_words_of, it, key)
                it["words"], it["lang"] = got["words"], got["language"]
            except MediaError:
                it["words_try"] = int(time.time())      # l'envoi réussit quand même ; réessai avant le prochain scénario
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


def _sound_text(it: dict) -> str:
    if "audio" not in it:
        return ""
    if not it["audio"]:
        return " Son : aucun (film muet)."
    talk = it.get("talk") or []
    if not talk:
        return " Son : ambiance seulement, aucun passage parlé net."
    shown = "; ".join(f"{a:.1f}–{b:.1f} s" for a, b in talk[:30]) + (" …" if len(talk) > 30 else "")
    said = ""
    if it.get("words"):     # transcrit : l'IA sait CE QUI est dit, et quand
        said = " Paroles (instant : mots) : " + " | ".join(f"{a:.1f} s {txt}" for a, _b, txt in it["words"][:400]) + (" …" if len(it["words"]) > 400 else "") + "."
    return f" Son : {len(talk)} passages sonores forts (parole probable, entre des silences) : {shown}.{said}"


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
                         + (f" Ce qu'on voit (instant : image) : {seen}" if seen else " (pas encore regardée : contenu inconnu)")
                         + _sound_text(it))
        elif it["kind"] == "photo":
            seen = " | ".join(x for _t, x in it.get("looks") or [])
            lines.append(f"- photo {it['id']} : « {it['name']} »" + (f" ({it['dims'][0]}×{it['dims'][1]})" if it.get("dims") else "")
                         + (f". Ce qu'on voit : {it.get('summary') or seen}" if (it.get("summary") or seen) else " (pas encore regardée)"))
        elif it["kind"] == "lottie":
            lines.append(f"- animation {it['id']} : « {Path(it['name']).stem} », {it['seconds']:.1f} s (Lottie : type lottie, media = cet identifiant)")
        elif it["kind"] == "music":
            lines.append(f"- musique {it['id']} : « {it['name']} », {it['seconds']:.0f} s" + (f", {it['bpm']:g} BPM (coupes calées sur ses temps forts)" if it.get("bpm") else ""))
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
    return {".jpg": "image/jpeg", ".json": "application/json", ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".aac": "audio/aac", ".wav": "audio/wav", ".ogg": "audio/ogg"}.get(path.suffix.lower(), "application/octet-stream")


def _base_url() -> str:
    base = (settings.unic_public_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise MediaError("Tes médias doivent être téléchargés par GitHub : indique l'adresse https du serveur (réglage UNIC_PUBLIC_URL).", 400)
    return base


def _has_own_lottie(s: dict) -> bool:
    """Une animation du patron (envoyée dans Mes médias) dans cette scène, son incrustation ou ses panneaux du Studio ?"""
    fx = [s, s.get("overlay"), *(s.get("panels") or [])]
    return any(isinstance(f, dict) and f.get("type") == "lottie" and f.get("media") for f in fx)


def to_engine(db: Session, spec: dict) -> dict:
    """Scénario du Studio -> forme du moteur : « my_clip » devient un clip avec lien secret, « phrases » un morceau de voix,
    « audio » la bande son. Les liens des médias utilisés s'ouvrent pour OPEN_HOURS (clic « Lancer » du patron en amont)."""
    if not any(s.get("type") in ("my_clip", "my_photo") or s.get("phrases") or _has_own_lottie(s) for s in spec.get("scenes") or []) and not spec.get("audio"):
        return {k: v for k, v in spec.items() if k != "captions"}
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
    caps = bool(spec.get("captions"))
    scenes = []
    for s in spec.get("scenes") or []:
        s = dict(s)
        ph = s.pop("phrases", None)
        words = None
        if caps and s.get("type") == "my_clip" and s.get("sound") and (by_id.get(s.get("media") or "") or {}).get("words"):   # parole du film
            a = float(s.get("start") or 0)
            words = scene_words(by_id[s["media"]]["words"], a, a + float(s["seconds"]) - float(s.get("freeze") or 0))
        if s.get("type") == "my_clip":   # plan monté par le moteur (scripts/video/edit.py)
            from app.video_studio import FOCUS
            eng = {"type": "clip", "url": link(s["media"], "clip"), "seconds": s["seconds"], "start": s.get("start", 0),
                   **{k: s[k] for k in ("speed", "grade", "zoom", "zoom_amount", "freeze", "transition", "sound") if k in s},
                   **({"overlay": s["overlay"]} if s.get("overlay") else {})}
            if s.get("focus") in FOCUS:
                eng["focus"] = {"x": FOCUS[s["focus"]][0], "y": FOCUS[s["focus"]][1]}
            if s.get("split_media"):
                eng["split"] = {"url": link(s["split_media"], "clip"), "start": s.get("split_start", 0)}
            if s.get("layout") == "split":
                eng["layout"] = "split"
            if s.get("panels"):        # instants du fichier -> instants dans le plan (+ avance d'une animation commencée avant)
                sp_, st = float(s.get("speed") or 1), float(s.get("start") or 0)
                eng["panels"] = [[round(max(0.0, p["at"] - st) / sp_, 2), round(max(0.0, st - p["at"]) / sp_, 2), {k: v for k, v in p.items() if k != "at"}]
                                 for p in s["panels"]]
                if s.get("overlay") and eng["panels"][0][0] > 0:
                    eng["panels"].insert(0, [0, 0, s["overlay"]])
            s = eng
        elif s.get("type") == "my_photo":   # photo du patron : scène photo (zoom lent, sans panoramique), lien secret
            s = {"type": "photo", "url": link(s["media"], "photo"), "seconds": s["seconds"], "caption": s.get("caption", ""), "direction": "in"}
        if ph and voice and voice.get("phrases"):
            i, j = ph
            s["voice"], s["voice_at"] = [voice["phrases"][i][0], voice["phrases"][j][1]], 0.25
            if caps and voice.get("words") and not words:      # voix off : ses mots, calés sur le moment où elle parle dans la scène
                words = scene_words(voice["words"], s["voice"][0], s["voice"][1], 0.25)
        if words:
            s["captions"] = words
        scenes.append(s)
    def lot(fx):        # animation du patron (scène, incrustation ou panneau) : lien secret, comme ses vidéos
        if isinstance(fx, dict) and fx.get("type") == "lottie" and fx.get("media"):
            fx = {**{k: v for k, v in fx.items() if k != "media"}, "url": link(fx["media"], "lottie")}
        return fx
    for k, s in enumerate(scenes):
        scenes[k] = s = lot(s)
        if s.get("overlay"):
            s["overlay"] = lot(s["overlay"])
        for p in s.get("panels") or []:
            if isinstance(p, list) and len(p) == 3:
                p[2] = lot(p[2])
    out = {k: v for k, v in spec.items() if k not in ("scenes", "audio", "captions")}
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
