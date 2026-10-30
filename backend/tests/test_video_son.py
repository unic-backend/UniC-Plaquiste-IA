"""Bande son du moteur vidéo (scripts/video/spec.py + sound.py) : musique, voix découpée par scène, clavier des textes tapés."""
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video"


def _load(name):
    sys.path.insert(0, str(ROOT))
    try:
        m = importlib.util.spec_from_file_location(f"video_{name}_son", ROOT / f"{name}.py")
        mod = importlib.util.module_from_spec(m)
        m.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(ROOT))


def test_bande_son_validee():
    sp = _load("spec")
    out = sp.clean({"audio": {"music": {"url": "https://cdn.example.com/m.mp3", "start": 9999, "volume": 7}, "voice": {"url": "https://cdn.example.com/v.mp3"},
                              "duck": "nimporte"},
                    "scenes": [{"type": "kinetic", "lines": ["A"], "voice": [14.3, 15.7], "voice_at": 0.3},
                               {"type": "kinetic", "lines": ["B"], "voice": [5, 2]},           # fin avant début : ignoré
                               {"type": "kinetic", "lines": ["C"], "voice": [0, 90]}]})        # plus de 60 s : ignoré
    au = out["audio"]
    assert au["music"] == {"url": "https://cdn.example.com/m.mp3", "start": 3600, "volume": 2} and au["voice"]["offset"] == 0
    assert au["keys"] is True and au["duck"] == "normal"
    assert out["scenes"][0]["voice"] == [14.3, 15.7] and out["scenes"][0]["voice_at"] == 0.3
    assert "voice" not in out["scenes"][1] and "voice" not in out["scenes"][2]
    assert "audio" not in sp.clean({"scenes": [{"type": "kinetic", "lines": ["A"]}]})               # sans bande son : vidéo muette comme avant
    for bad in ("http://169.254.169.254/m.mp3", "https://localhost/m.mp3", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            sp.clean({"audio": {"music": {"url": bad}}, "scenes": [{"type": "kinetic", "lines": ["A"]}]})


def test_clavier_au_rythme_des_lettres():
    so = _load("sound")
    html = (ROOT / "scenes.html").read_text(encoding="utf-8")
    assert f"const CPS = {so.CPS};" in html and "tt += l.length / CPS + .3" in html                 # même rythme que l'affichage
    t = so.key_times({"type": "typewriter", "lines": ["AB C", "D"]}, start=10, seconds=5)
    assert t == [10.35, round(10.35 + 1 / 14, 4), round(10.35 + 3 / 14, 4), round(10.35 + 4 / 14 + 0.3, 4)]   # l'espace ne claque pas
    clip = {"type": "clip", "overlay": {"type": "typewriter", "lines": ["XY"]}}
    assert so.key_times(clip, 0, 3) == [0.35, round(0.35 + 1 / 14, 4)]
    assert so.key_times({"type": "slogan", "lines": ["9"]}, 0, 6) == [2.4]
    assert so.key_times({"type": "kinetic", "lines": ["A"]}, 0, 3) == []
    assert so.key_times({"type": "typewriter", "lines": ["ABCDEFGHIJ" * 6]}, 0, 1.0) and max(so.key_times({"type": "typewriter", "lines": ["ABCDEFGHIJ" * 6]}, 0, 1.0)) < 1.0


def test_voix_placee_par_scene_et_par_troncon():
    so = _load("sound")
    scenes = [(0.0, 4.0, {"voice": [0.0, 2.4], "voice_at": 0.5}), (4.0, 3.0, {})]
    assert so.voice_pieces(scenes, {"voice": {}}, 0, 7) == [(0.5, 0.0, 2.4)]
    whole = [(0.0, 5.0, {})]
    assert so.voice_pieces(whole, {"voice": {"offset": 2}}, 0, 5) == [(2.0, 0.0, 3600.0)]          # piste entière, décalée
    assert so.voice_pieces(whole, {"voice": {"offset": 2}}, 90, 5) == [(0.0, 88.0, 3600.0)]        # 2e tronçon : reprend où il faut
    assert so.voice_pieces(whole, {"voice": {"offset": 50}}, 0, 5) == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_mixage_ffmpeg(tmp_path):
    so = _load("sound")
    mus, voi = tmp_path / "m.wav", tmp_path / "v.wav"
    for f, hz in ((mus, 220), (voi, 660)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration=8", str(f)], check=True)
    audio = {"music": {"start": 0, "volume": 1}, "voice": {"volume": 1}, "keys": True, "duck": "normal"}
    scenes = [(0.0, 3.0, {"type": "typewriter", "lines": ["JOJ"], "voice": [0, 1.0], "voice_at": 0.2}), (3.0, 3.0, {"type": "kinetic"})]
    wav = so.build(audio, scenes, {"music": mus, "voice": voi}, 0, 6.0, tmp_path, True, True)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)], capture_output=True, text=True).stdout
    assert abs(float(d) - 6.0) < 0.05                                                                # la musique va jusqu'au bout, même après la voix
    silent = so.build({"keys": True}, [(0.0, 2.0, {"type": "kinetic"})], {}, 0, 2.0, tmp_path, False, False)
    assert silent.exists()                                                                           # rien à jouer : piste muette (assemblage sans ré-encodage)
