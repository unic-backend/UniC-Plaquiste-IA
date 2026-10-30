"""Médias du patron dans le Studio vidéo : envoi, phrases d'une voix, liens secrets ouverts au lancement seulement, scénario -> moteur."""
import asyncio
import importlib.util
import io
import pathlib
import shutil
import subprocess

import pytest

from app import video_media as vm
from app import video_studio as vs

FFMPEG = shutil.which("ffmpeg") is not None


def test_phrases_depuis_le_journal_de_silence():
    log = "silence_start: 2.4\nsilence_end: 2.85\nsilence_start: 5.04 | x\nsilence_end: 5.5\n"
    assert vm.phrases_from_log(log, 8.0) == [[0.0, 2.4], [2.85, 5.04], [5.5, 8.0]]
    assert vm.phrases_from_log("", 3.0) == [[0.0, 3.0]]
    assert vm.phrases_from_log("silence_start: 0\nsilence_end: 0.5\n", 2.0) == [[0.5, 2.0]]   # silence au début : ignoré


def test_texte_de_la_voix_en_phrases():
    assert vm.split_script("Il y a des moments… Des rendez-vous.\nL'Afrique accueille !  Dakar célèbre.") == [
        "Il y a des moments…", "Des rendez-vous.", "L'Afrique accueille !", "Dakar célèbre."]


class _Up:
    def __init__(self, name, data):
        self.filename, self._b = name, io.BytesIO(data)

    async def read(self, n=-1):
        return self._b.read(n)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.database import SessionLocal
    monkeypatch.setattr(vm.settings, "unic_data_dir", str(tmp_path))
    with TestClient(main.app):
        with SessionLocal() as s:
            from app.models import AppSetting
            row = s.get(AppSetting, vm.KEY)
            if row:
                s.delete(row)
                s.commit()
            yield s


def _sound(path, spec):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *spec, str(path)], check=True)
    return path.read_bytes()


def test_refus_format_et_fichier_illisible(db):
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.exe", b"MZ"), "clip"))
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.mp4", b"pas une video"), "clip"))
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.mp3", b"x"), "inconnu"))
    assert vm.listing(db) == [] and not list((vm._dir()).iterdir())        # rien d'enregistré, aucun fichier laissé


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_envoi_phrases_liens_et_moteur(db, tmp_path, monkeypatch):
    voice = _sound(tmp_path / "v.wav", ["-f", "lavfi", "-i", "sine=f=440:d=1.5", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-f", "lavfi", "-i", "sine=f=440:d=1.2",
                                        "-filter_complex", "[1]atrim=0:0.8[s];[0][s][2]concat=n=3:v=0:a=1"])
    clip = _sound(tmp_path / "c.mp4", ["-f", "lavfi", "-i", "testsrc=d=6:s=320x240:r=25", "-pix_fmt", "yuv420p"])
    music = _sound(tmp_path / "m.mp3", ["-f", "lavfi", "-i", "sine=f=220:d=20"])
    v = asyncio.run(vm.add(db, _Up("voix.wav", voice), "voice", "Première phrase. Deuxième phrase."))
    c = asyncio.run(vm.add(db, _Up("chantier.mp4", clip), "clip"))
    m = asyncio.run(vm.add(db, _Up("kaaro.mp3", music), "music"))
    assert len(v["phrases"]) == 2 and v["phrases"][1]["text"] == "Deuxième phrase."
    assert 5.5 < c["seconds"] < 6.5 and "token" not in c                                       # le jeton ne sort jamais vers l'appli
    media = vm.items_by_id(db)
    assert "Deuxième phrase" in vm.catalog_text(db) and c["id"] in vm.catalog_text(db)

    spec = vs.build_spec("vertical", [
        {"type": "my_clip", "media": c["id"], "start": 99, "seconds": 2, "phrases": [0, 0], "overlay": {"type": "kinetic", "lines": ["Des mains", "expertes."]}},
        {"type": "my_clip", "media": "000000000000"},                                             # inconnue : écartée
        {"type": "kinetic", "lines": ["Fin"], "phrases": [0, 1]},                                 # phrase 0 déjà dite : refusé
        {"type": "slogan", "l1": "A", "l2": "B", "phrases": [1, 1]}],
        [], media=media, audio={"music": m["id"], "music_start": 9999, "voice": v["id"], "duck": "strong"})
    a, k, sl = spec["scenes"]
    assert a["start"] == 5.0 or a["start"] <= c["seconds"] - 1                                     # passage borné par la durée du fichier
    assert a["phrases"] == [0, 0] and "phrases" not in k and sl["phrases"] == [1, 1]
    assert spec["audio"]["music_start"] <= 15 and spec["audio"]["duck"] == "strong"
    assert vs.build_spec("vertical", spec["scenes"], [], media=media, audio=spec["audio"]) == spec   # aller-retour stable

    tok = vm._load(db)[0]["token"]
    assert vm.public_path(db, tok) is None                                                       # fermé tant que rien n'est lancé
    monkeypatch.setattr(vm.settings, "unic_public_url", "")
    with pytest.raises(vm.MediaError):
        vm.to_engine(db, spec)                                                                   # sans adresse https : refus clair
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    eng = vm.to_engine(db, spec)
    clip0 = eng["scenes"][0]
    assert clip0["type"] == "clip" and clip0["url"].startswith("https://unic.example.com/api/public/video-media/") and clip0["voice"][0] == 0.0
    assert eng["audio"]["music"]["url"] != eng["audio"]["voice"]["url"] and eng["audio"]["duck"] == "strong"
    assert vm.public_path(db, clip0["url"].rsplit("/", 1)[1]) is not None                       # ouvert pour cette fabrication

    p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    mod = importlib.util.spec_from_file_location("video_spec_media", p)
    eng_mod = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(eng_mod)
    out = eng_mod.clean(eng)                                                                     # le moteur accepte
    assert out["scenes"][0]["start"] == a["start"] and out["scenes"][0]["voice"] and out["audio"]["keys"] is True

    vm.hide(db, c["id"])
    assert all(x["id"] != c["id"] for x in vm.listing(db)) and vm.public_path(db, clip0["url"].rsplit("/", 1)[1]) is None
    assert (vm._dir() / f"{c['id']}.mp4").exists()                                              # retiré, jamais supprimé


def test_route_publique_fermee(db):
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as cl:
        assert cl.get("/api/public/video-media/nimportequoi").status_code == 404
