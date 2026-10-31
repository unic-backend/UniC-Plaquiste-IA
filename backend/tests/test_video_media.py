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


def test_instants_regardes_et_lecture_de_la_vision():
    assert vm.frame_times(80, 8) == [5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0, 75.0]
    assert vm.frame_times(1.0, 8) == [0.2, 0.8] and vm.frame_times(0) == []                       # vidéo très courte : moins d'images
    txt = ("**#0 :** Vue large du Stade Abdoulaye Wade, panneau « DAKAR 2026 »\n#1 - Équipe posant des plaques BA13, net\n"
           "#1 : doublon ignoré\n#9 : hors liste\n2) Couloir <script>sombre</script>\nRésumé : Chantier BA13 au stade, équipe au travail.")
    looks, summary = vm.parse_looks(txt, [5.0, 15.0, 25.0])
    assert [t for t, _ in looks] == [5.0, 15.0, 25.0]
    assert looks[0][1].startswith("Vue large du Stade Abdoulaye Wade") and "<" not in looks[2][1]
    assert summary == "Chantier BA13 au stade, équipe au travail."
    assert vm.parse_looks("", [1.0]) == ([], "")


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_l_ia_regarde_la_video_et_s_en_sert(db, tmp_path, monkeypatch):
    from app import higgsfield, vision
    clip = _sound(tmp_path / "c.mp4", ["-f", "lavfi", "-i", "testsrc=d=8:s=320x240:r=25", "-pix_fmt", "yuv420p"])
    calls = []

    def describe(frames):
        calls.append(len(frames))
        assert all(p.exists() and p.stat().st_size > 0 for _, p in frames)                     # vraies images extraites
        return "\n".join(f"#{i} : mire de couleurs numéro {i}" for i in range(len(frames))) + "\nRésumé : Mire de test."

    monkeypatch.setattr(vision, "disponible", lambda: False)
    old = asyncio.run(vm.add(db, _Up("ancienne.mp4", clip), "clip"))                            # envoyée sans vision : pas regardée
    assert old["looks"] == [] and "pas encore regardée" in vm.catalog_text(db)
    monkeypatch.setattr(vision, "disponible", lambda: True)
    monkeypatch.setattr(vision, "describe_frames", describe)
    new = asyncio.run(vm.add(db, _Up("stade.mp4", clip), "clip"))                                # regardée dès l'envoi
    assert new["summary"] == "Mire de test." and len(new["looks"]) == vm.LOOK_FRAMES and new["looks"][0] == {"t": 0.5, "text": "mire de couleurs numéro 0"}
    assert vm.ensure_looks(db) == 1 and calls == [8, 8] and vm.ensure_looks(db) == 0              # l'ancienne rattrapée, une seule fois
    cat = vm.catalog_text(db)
    assert "0.5 s : mire de couleurs numéro 0" in cat and "Résumé : Mire de test." in cat and "pas encore regardée" not in cat

    monkeypatch.setattr(vision, "describe_frames", lambda frames: "")                           # vision en panne : réessai plus tard, pas en boucle
    third = asyncio.run(vm.add(db, _Up("x.mp4", clip), "clip"))
    assert third["looks"] == [] and vm.ensure_looks(db) == 0

    f = vm.frame_path(db, new["id"], 3.3)
    assert f and f.read_bytes()[:2] == b"\xff\xd8" and f.name.endswith("-35.jpg")                # vraie image JPEG, arrondie à la demi-seconde
    assert vm.frame_path(db, new["id"], float("nan")) is None and vm.frame_path(db, "000000000000", 1) is None

    seen = {}
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(higgsfield, "status", lambda d: {"connected": False})
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: seen.update(system=system, user=user) or {
        "scenes": [{"type": "my_clip", "media": new["id"], "start": 2.5, "seconds": 3}, {"type": "my_clip", "media": new["id"], "start": 6, "seconds": 2}]})
    p = vs.plan(db, "", "vertical")                                                              # case vide + vidéos : SES vidéos, pas le modèle fixe
    assert "montage de ses vidéos" in seen["user"] and "mire de couleurs numéro 3" in seen["user"] and "CŒUR du montage" in seen["system"]
    assert [s["type"] for s in p["spec"]["scenes"]] == ["my_clip", "my_clip"] and p["spec"]["scenes"][1]["start"] == 6


def test_route_vignette(db):
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as cl:
        assert cl.get("/api/website/video/media/000000000000/frame?t=1").status_code in (401, 403, 404)
        assert cl.get("/api/website/video/media/..%2Fx/frame").status_code in (401, 403, 404)
