"""Bande son d'un tronçon : musique (baissée automatiquement sous la voix et sous la parole filmée), voix découpée scène par scène,
son gardé des films, son du clavier des textes tapés.

Pas de dépendance en plus : ffmpeg pour le mélange, la bibliothèque standard pour le clavier. Le clavier suit EXACTEMENT le rythme
des scènes « machine à écrire » de scenes.html (14 caractères/s, 0,3 s entre deux lignes) : le son tombe sur chaque lettre affichée.
"""
from __future__ import annotations

import math
import random
import struct
import subprocess
import wave
from pathlib import Path

CPS = 14            # scenes.html : const CPS = 14
LINE_GAP = 0.3      # scenes.html : tt += l.length / CPS + .3
SR = 44100
DUCK = {"light": 3, "normal": 6, "strong": 12}   # taux de compression de la musique quand la voix parle


def typed_scene(sc: dict) -> dict | None:
    """Scène (ou incrustation d'un clip) qui tape du texte : rend {lines, t0} ou None."""
    if not isinstance(sc, dict):
        return None
    if sc.get("type") == "clip":
        return typed_scene(sc.get("overlay"))
    if sc.get("type") == "typewriter":
        return {"lines": sc.get("lines") or [], "t0": 0.35}
    if sc.get("type") == "slogan":
        return {"lines": sc.get("lines") or [], "t0": 2.4}
    return None


def key_times(sc: dict, start: float, seconds: float) -> list[float]:
    """Instants (dans le tronçon) où une lettre s'affiche : un clic par caractère visible, jamais après la fin de la scène."""
    ty = typed_scene(sc)
    if not ty:
        return []
    out, tt = [], ty["t0"]
    for line in ty["lines"]:
        for k, ch in enumerate(line):
            t = tt + k / CPS
            if ch != " " and t < seconds - 0.05:
                out.append(round(start + t, 4))
        tt += len(line) / CPS + LINE_GAP
    return out


def _click(rng: random.Random) -> list[float]:
    """Un clic de touche : bruit très bref (aigu) + petit choc sourd, légèrement différent à chaque frappe."""
    n = int(0.045 * SR)
    f = rng.uniform(150, 230)
    g = rng.uniform(0.55, 1.0)
    prev, out = 0.0, []
    for i in range(n):
        t = i / SR
        noise = rng.uniform(-1, 1)
        hp = noise - prev            # passe-haut très simple : garde le « tic » sec
        prev = noise
        out.append(g * (0.5 * hp * math.exp(-t * 380) + 0.45 * math.sin(2 * math.pi * f * t) * math.exp(-t * 90)))
    return out


def clicks_wav(path: Path, times: list[float], total: float, seed: int = 7) -> None:
    """Piste mono 16 bits : les clics aux instants donnés, silence ailleurs."""
    n = max(1, int(total * SR))
    buf = [0.0] * n
    rng = random.Random(seed)
    for t in times:
        c = _click(rng)
        i0 = int(t * SR)
        for j, v in enumerate(c):
            if 0 <= i0 + j < n:
                buf[i0 + j] += v
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 0.6 * 32767)))) for v in buf))


def voice_pieces(scenes: list[tuple[float, float, dict]], audio: dict, chunk_offset: float, total: float) -> list[tuple[float, float, float]]:
    """Morceaux de voix à jouer dans ce tronçon : (instant dans le tronçon, début dans la piste voix, fin dans la piste voix).
    Une scène peut porter « voice »: [début, fin] (morceau de la piste) et « voice_at » (décalage dans la scène).
    Sans aucun morceau désigné, toute la piste se joue à partir de « voice.offset » secondes du début de la vidéo."""
    pieces = []
    for start, secs, sc in scenes:
        seg = sc.get("voice")
        if seg:
            a, b = seg
            at = start + float(sc.get("voice_at") or 0)
            pieces.append((at, a, min(b, a + max(0.0, secs - float(sc.get("voice_at") or 0)) + 1.5)))   # peut déborder un peu sur la scène suivante
    if pieces or not audio.get("voice"):
        return pieces
    off = float(audio["voice"].get("offset") or 0)
    local = off - chunk_offset                     # instant de début de la voix dans ce tronçon
    if local >= total:
        return []
    if local >= 0:
        return [(local, 0.0, 3600.0)]
    return [(0.0, -local, 3600.0)]


def has_audio(path: Path) -> bool:
    """Le fichier a-t-il une piste son ? (un film sans son ne doit pas faire échouer le mélange)"""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


def build(audio: dict, scenes: list[tuple[float, float, dict]], files: dict, chunk_offset: float, total: float,
          work: Path, fade_in: bool, fade_out: bool, clips: list[tuple[float, Path, float, float]] | None = None) -> Path:
    """Fabrique la bande son WAV du tronçon. `files` : chemins locaux téléchargés {"music": ..., "voice": ...}.
    `clips` : son gardé des films [(instant dans le tronçon, fichier, début dans le fichier, durée)] ; mélangé avec la voix :
    la musique baisse aussi sous la parole filmée."""
    inputs, chains, mix = [], [], []
    if files.get("music"):
        m = audio["music"]
        inputs += ["-ss", f"{float(m.get('start') or 0) + chunk_offset:.3f}", "-t", f"{total + 0.5:.3f}", "-i", str(files["music"])]
        chains.append(f"[{inputs.count('-i') - 1}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={0.45 * float(m.get('volume', 1)):.3f}[mus]")
    pieces = voice_pieces(scenes, audio, chunk_offset, total) if files.get("voice") else []
    labels = []
    if pieces:
        inputs += ["-i", str(files["voice"])]
        vin = inputs.count("-i") - 1
        vol = float(audio["voice"].get("volume", 1))
        for k, (at, a, b) in enumerate(pieces):
            ms = int(round(at * 1000))
            chains.append(f"[{vin}:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates={SR}:channel_layouts=stereo,"
                          f"afade=t=in:d=0.03,adelay={ms}|{ms},volume={vol:.3f}[v{k}]")
            labels.append(f"[v{k}]")
    for k, (at, path, a, dur) in enumerate(clips or []):     # son des films : fondus très courts aux coupes (pas de clic)
        inputs += ["-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(path)]
        ms = int(round(at * 1000))
        chains.append(f"[{inputs.count('-i') - 1}:a]aformat=sample_rates={SR}:channel_layouts=stereo,afade=t=in:d=0.04,"
                      f"afade=t=out:st={max(0.0, dur - 0.06):.3f}:d=0.06,adelay={ms}|{ms}[c{k}]")
        labels.append(f"[c{k}]")
    if labels:
        chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,asplit=2[vox][sc0]")
        chains.append("[sc0]apad[sc]")   # sans fin : sinon la musique s'arrêterait avec la dernière phrase
    if files.get("music"):
        if labels:
            ratio = DUCK.get(audio.get("duck", "normal"), 6)
            chains.append(f"[mus][sc]sidechaincompress=threshold=0.02:ratio={ratio}:attack=40:release=450[mduck]")
            mix.append("[mduck]")
        else:
            mix.append("[mus]")
    if labels:
        mix.append("[vox]")
    times = [t for start, secs, sc in scenes for t in key_times(sc, start, secs)] if audio.get("keys") else []
    if times:
        kw = work / "keys.wav"
        clicks_wav(kw, times, total)
        inputs += ["-i", str(kw)]
        ki = inputs.count("-i") - 1
        chains.append(f"[{ki}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume=1.8[keys]")
        mix.append("[keys]")
    out = work / "sound.wav"
    if not mix:   # rien à jouer : silence (tous les tronçons doivent avoir une piste son pour l'assemblage sans ré-encodage)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{total:.3f}", str(out)], check=True)
        return out
    fades = (",afade=t=in:d=1.0" if fade_in else "") + (f",afade=t=out:st={max(0.0, total - 2.5):.3f}:d=2.5" if fade_out else "")
    chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:dropout_transition=0,volume=1.6,alimiter=limit=0.89:level=disabled,"
                  f"apad,atrim=end={total:.3f}{fades}[out]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[out]",
                    "-ar", str(SR), "-ac", "2", str(out)], check=True)
    return out
