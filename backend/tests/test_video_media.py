"""Médias du patron dans le Studio vidéo : envoi, phrases d'une voix, liens secrets ouverts au lancement seulement, scénario -> moteur."""
import asyncio
import json
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
    assert "regarde et écoute ses médias" in seen["user"] and "mire de couleurs numéro 3" in seen["user"] and "matière de la vidéo" in seen["system"]
    assert [s["type"] for s in p["spec"]["scenes"]] == ["my_clip", "my_clip"] and p["spec"]["scenes"][1]["start"] == 6


def test_route_vignette(db):
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as cl:
        assert cl.get("/api/website/video/media/000000000000/frame?t=1").status_code in (401, 403, 404)
        assert cl.get("/api/website/video/media/..%2Fx/frame").status_code in (401, 403, 404)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_l_ia_monte_ses_films_et_laisse_les_photos(db, tmp_path, monkeypatch):
    from app import higgsfield
    clip = _sound(tmp_path / "c.mp4", ["-f", "lavfi", "-i", "testsrc=d=10:s=320x240:r=25", "-pix_fmt", "yuv420p"])
    a = asyncio.run(vm.add(db, _Up("avant.mp4", clip), "clip"))
    b = asyncio.run(vm.add(db, _Up("apres.mp4", clip), "clip"))
    media = vm.items_by_id(db)
    raw = [{"type": "my_clip", "media": a["id"], "start": 6, "seconds": 30, "speed": 0.25, "grade": "night", "focus": "top", "zoom": "punch", "zoom_amount": 7,
            "freeze": 1, "transition": "flash", "split_media": b["id"], "split_start": 99},
           {"type": "my_clip", "media": a["id"], "speed": 3, "grade": "sepia", "focus": "nulle-part", "transition": "fondu", "split_media": "000000000000"}]
    one, two = vs.build_spec("vertical", raw, [], media=media)["scenes"]
    assert one["seconds"] == 17.0                                                                     # 4 s de film ×4 au ralenti + 1 s figée : jamais au-delà du fichier
    assert (one["speed"], one["grade"], one["focus"], one["zoom"], one["zoom_amount"], one["freeze"], one["transition"]) == (0.25, "night", "top", "punch", 1.6, 1.0, "flash")
    assert one["split_media"] == b["id"] and one["split_start"] == 9.0
    assert two["speed"] == 3 and not {"grade", "focus", "transition", "split_media"} & set(two)          # inconnu : ignoré
    spec = {"format": "vertical", "theme": "unic", "scenes": [one, two]}
    assert vs.build_spec("vertical", spec["scenes"], [], media=media)["scenes"] == spec["scenes"]       # aller-retour stable (appli -> serveur)
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    eng = vm.to_engine(db, spec)["scenes"][0]
    assert eng["focus"] == {"x": 0.5, "y": 0.2} and eng["split"]["url"].startswith("https://unic.example.com/api/public/video-media/") and eng["split"]["start"] == 9.0
    p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    mod = importlib.util.spec_from_file_location("video_spec_montage_studio", p)
    sp = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(sp)
    out = sp.clean(vm.to_engine(db, spec))["scenes"][0]                                                # le moteur accepte tout le montage
    assert (out["speed"], out["grade"], out["zoom"], out["freeze"], out["transition"]) == (0.25, "night", "punch", 1.0, "flash") and out["split"]["start"] == 9.0

    seen = {}
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(higgsfield, "status", lambda d: {"connected": False})
    story = {"scenes": [{"type": "photo", "image": "hero-01.webp"}, {"type": "gallery", "images": ["hero-01.webp", "hero-02.webp"]},
                        {"type": "kinetic", "lines": ["Dakar"], "image": "hero-01.webp", "reveal": True}, {"type": "my_clip", "media": a["id"], "seconds": 3}]}
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: seen.update(system=system, user=user) or story)
    p1 = vs.plan(db, "Pub JOJ de 30 s avec mes vidéos", "vertical")
    assert [s["type"] for s in p1["spec"]["scenes"]] == ["kinetic", "my_clip"] and "image" not in p1["spec"]["scenes"][0]   # ni photos ni galerie du site
    assert "Photos (noms exacts)" not in seen["user"] and "LIBRE" in seen["system"] and "aucune photo, aucun chiffre" in seen["user"]
    p2 = vs.plan(db, "Pub JOJ avec mes vidéos et quelques photos du site", "vertical")
    assert "Photos (noms exacts)" in seen["user"] and "my_clip" in [s["type"] for s in p2["spec"]["scenes"]]   # demandées : permises


def test_passages_parles_a_garder():
    assert vm.merge_talk([[1.0, 2.0], [2.2, 3.0], [5.0, 5.2], [7.0, 9.95]], 10.0) == [[0.9, 3.1], [6.9, 10.0]]   # pause courte gardée, bribe écartée
    assert vm.merge_talk([], 5.0) == []


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_son_du_film_et_coupe_des_silences(db, tmp_path, monkeypatch):
    talk = _sound(tmp_path / "t.mp4", ["-f", "lavfi", "-i", "testsrc=d=6:s=320x240:r=25", "-f", "lavfi", "-i",
                                       "aevalsrc='if(lt(t,1.5)+between(t,3,5),0.5*sin(2*PI*300*t),0)':d=6:s=44100", "-pix_fmt", "yuv420p", "-shortest"])
    mute = _sound(tmp_path / "m.mp4", ["-f", "lavfi", "-i", "testsrc=d=4:s=320x240:r=25", "-pix_fmt", "yuv420p"])
    t = asyncio.run(vm.add(db, _Up("parle.mp4", talk), "clip"))
    m = asyncio.run(vm.add(db, _Up("muet.mp4", mute), "clip"))
    assert t["audio"] is True and t["talk"] == 2 and m["audio"] is False and m["talk"] == 0
    media = vm.items_by_id(db)
    assert media[t["id"]]["talk"] == [[0.0, 1.6], [2.9, 5.1]]
    cat = vm.catalog_text(db)
    assert "2 passages sonores forts" in cat and "0.0–1.6 s" in cat and "Son : aucun (film muet)" in cat

    raw = [{"type": "my_clip", "media": t["id"], "jumpcut": True, "grade": "warm", "transition": "flash", "zoom": "in",
            "overlay": {"type": "kinetic", "lines": ["Bonjour"]}},
           {"type": "my_clip", "media": m["id"], "sound": True, "seconds": 2},                      # film muet : pas de son demandé au moteur
           {"type": "my_clip", "media": t["id"], "sound": True, "speed": 0.5, "seconds": 2}]          # ralenti : jamais de son
    sc = vs.build_spec("vertical", raw, [], media=media)["scenes"]
    a, b = sc[0], sc[1]
    assert [(x["start"], x["seconds"]) for x in sc[:2]] == [(0.0, 1.6), (2.9, 2.2)]                  # les silences ont disparu
    assert a["sound"] and b["sound"] and a["transition"] == "flash" and b["transition"] == "cut" and a["grade"] == b["grade"] == "warm"
    assert "overlay" in a and "overlay" not in b and a["zoom"] == "in" and "zoom" not in b
    assert "sound" not in sc[2] and "sound" not in sc[3] and sc[3]["speed"] == 0.5
    assert vs.build_spec("vertical", sc, [], media=media)["scenes"] == sc                            # aller-retour stable
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    eng = vm.to_engine(db, {"format": "vertical", "theme": "unic", "scenes": sc})["scenes"]
    assert eng[0]["sound"] is True and eng[1]["transition"] == "cut"

    items = vm._load(db)                                                                             # film envoyé avant cette fonction
    for it in items:
        it.pop("audio", None), it.pop("talk", None)
    vm._save(db, items)
    assert vm.ensure_sound(db) == 2 and vm.ensure_sound(db) == 0 and vm.items_by_id(db)[t["id"]]["talk"] == [[0.0, 1.6], [2.9, 5.1]]


def test_coupe_des_silences_longue_parole():
    it = {"id": "a" * 12, "kind": "clip", "seconds": 70.0, "audio": True, "talk": [[0.0, 65.0]]}
    sc = vs.build_spec("vertical", [{"type": "my_clip", "media": it["id"], "jumpcut": True}], [], media={it["id"]: it})["scenes"]
    assert [(x["start"], x["seconds"]) for x in sc] == [(0.0, 30.0), (30.0, 30.0), (60.0, 5.0)]     # parole sans pause : plans de 30 s collés
    assert [x.get("transition") for x in sc] == [None, "cut", "cut"]


def test_transcription_elevenlabs(monkeypatch, db):
    import httpx
    from app import voice
    calls = []

    def http(method, path, key, timeout=60, **kw):
        calls.append(kw["data"]["model_id"])
        if kw["data"]["model_id"] == "scribe_v2":
            return httpx.Response(422, json={"detail": {"message": "Invalid model_id"}})
        return httpx.Response(200, json={"language_code": "fra", "words": [
            {"text": "Bonjour", "start": 0.1, "end": 0.5, "type": "word"}, {"text": " ", "start": 0.5, "end": 0.55, "type": "spacing"},
            {"text": "<i>Dakar</i>", "start": 0.55, "end": 1.0, "type": "word"}, {"text": "(rires)", "start": 1, "end": 2, "type": "audio_event"},
            {"text": "x", "start": "?", "end": 1, "type": "word"}]})
    monkeypatch.setattr(voice, "api_key", lambda d: "cle")
    monkeypatch.setattr(voice, "_http", http)
    got = voice.transcribe(db, b"mp3")
    assert calls == ["scribe_v2", "scribe_v1"] and got == {"language": "fra", "words": [[0.1, 0.5, "Bonjour"], [0.55, 1.0, "iDakar/i"]]}
    monkeypatch.setattr(voice, "_http", lambda *a, **k: httpx.Response(401, json={"detail": "bad"}))
    with pytest.raises(voice.VoiceError):
        voice.transcribe(db, b"mp3")
    monkeypatch.setattr(voice, "api_key", lambda d: "")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe(db, b"mp3")
    assert e.value.status == 409


def test_mots_d_une_scene():
    w = [[1.0, 1.4, "a"], [2.0, 2.4, "b"], [5.0, 5.5, "c"]]
    assert vm.scene_words(w, 1.9, 5.0) == [[0.1, 0.5, "b"]] and vm.scene_words(w, 1.0, 9, 0.25) == [[0.25, 0.65, "a"], [1.25, 1.65, "b"], [4.25, 4.75, "c"]]


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_sous_titres_du_film_et_de_la_voix(db, tmp_path, monkeypatch):
    from app import voice
    talk = _sound(tmp_path / "t.mp4", ["-f", "lavfi", "-i", "testsrc=d=6:s=320x240:r=25", "-f", "lavfi", "-i", "sine=f=300:d=6", "-pix_fmt", "yuv420p", "-shortest"])
    vo = _sound(tmp_path / "v.wav", ["-f", "lavfi", "-i", "sine=f=440:d=1.5", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-f", "lavfi", "-i", "sine=f=440:d=1.2",
                                     "-filter_complex", "[1]atrim=0:0.8[s];[0][s][2]concat=n=3:v=0:a=1"])
    c = asyncio.run(vm.add(db, _Up("parle.mp4", talk), "clip"))
    v = asyncio.run(vm.add(db, _Up("voix.wav", vo), "voice", "Une phrase. Deux phrases."))
    sent = []

    def tr(d, audio, name, key=""):
        sent.append(audio[:3])
        return {"language": "fra", "words": [[0.2, 0.6, "Bonjour"], [0.7, 1.1, "Dakar"], [3.0, 3.4, "Merci"]]}
    monkeypatch.setattr(voice, "transcribe", tr)
    monkeypatch.setattr(voice, "api_key", lambda d: "cle")
    assert vm.transcribe(db, c["id"])["words"] == 3 and vm.transcribe(db, v["id"])["words"] == 3
    assert all(x in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") for x in sent)                    # seul le son part (mp3), jamais l'image
    with pytest.raises(vm.MediaError):
        vm.transcribe(db, "000000000000")
    assert "Paroles (instant : mots) : 0.2 s Bonjour" in vm.catalog_text(db)
    media = vm.items_by_id(db)
    raw = [{"type": "my_clip", "media": c["id"], "start": 0.5, "seconds": 3, "sound": True}, {"type": "kinetic", "lines": ["Voix"], "phrases": [1, 1]}]
    spec = vs.build_spec("vertical", raw, [], media=media, audio={"voice": v["id"]})
    assert spec["captions"] is True                                                                   # mots disponibles : oui par défaut
    off = vs.build_spec("vertical", spec["scenes"], [], media=media, audio=spec["audio"], captions=False)
    assert off["captions"] is False and vs.build_spec("vertical", off["scenes"], [], media=media, audio=off["audio"], captions=off["captions"]) == off
    assert "captions" not in vs.build_spec("vertical", [{"type": "kinetic", "lines": ["A"]}], [], media=media)   # rien à sous-titrer : pas d'option
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    eng = vm.to_engine(db, spec)
    a, k = eng["scenes"]
    assert a["captions"] == [[0.2, 0.6, "Dakar"], [2.5, 2.9, "Merci"]] and "captions" not in eng      # mots du passage choisi (0,5 s → 3,5 s)
    ph = media[v["id"]]["phrases"][1]
    assert k["captions"] == vm.scene_words(media[v["id"]]["words"], ph[0], ph[1], 0.25)              # voix off : calés sur sa phrase
    assert all("captions" not in x for x in vm.to_engine(db, off)["scenes"])                          # coupés par le patron
    p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    mod = importlib.util.spec_from_file_location("video_spec_caps", p)
    sp = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(sp)
    assert sp.clean(eng)["scenes"][0]["caps"] == [[0.2, 0.85, "Dakar"], [2.5, 3.0, "Merci"]]            # cartons prêts (bornés à la scène)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_sous_titres_automatiques(db, tmp_path, monkeypatch):
    from app import voice
    talk = _sound(tmp_path / "t.mp4", ["-f", "lavfi", "-i", "testsrc=d=6:s=320x240:r=25", "-f", "lavfi", "-i",
                                       "aevalsrc='if(lt(t,1.5)+between(t,3,5),0.5*sin(2*PI*300*t),0)':d=6:s=44100", "-pix_fmt", "yuv420p", "-shortest"])
    noise = _sound(tmp_path / "n.mp4", ["-f", "lavfi", "-i", "testsrc=d=4:s=320x240:r=25", "-f", "lavfi", "-i", "anoisesrc=d=4:a=0.3", "-pix_fmt", "yuv420p", "-shortest"])
    calls = []
    monkeypatch.setattr(voice, "api_key", lambda d: "cle")
    monkeypatch.setattr(voice, "transcribe", lambda d, audio, name, key="": calls.append(key) or {"language": "fra", "words": [[0.2, 0.6, "Salut"]]})
    t = asyncio.run(vm.add(db, _Up("parle.mp4", talk), "clip"))
    n = asyncio.run(vm.add(db, _Up("chantier.mp4", noise), "clip"))
    assert t["words"] == 1 and "words" not in n and calls == ["cle"]                       # parlé : sous-titré sans clic ; bruit continu : rien (crédit gardé)
    assert vm.wants_words({"kind": "clip", "audio": True, "talk": [[0, 4]], "seconds": 4, "summary": "Un homme parle face caméra."})
    assert not vm.wants_words({"kind": "voice", "seconds": 4000})                           # trop long : bouton seulement
    vm.set_auto_words(db, False)
    assert vm.auto_words(db) is False
    t2 = asyncio.run(vm.add(db, _Up("parle2.mp4", talk), "clip"))
    assert "words" not in t2 and vm.ensure_words(db) == 0 and len(calls) == 1               # réglage coupé : jamais sans clic
    vm.set_auto_words(db, True)
    monkeypatch.setattr(voice, "transcribe", lambda d, audio, name, key="": (_ for _ in ()).throw(voice.VoiceError("quota", 429)))
    assert vm.ensure_words(db) == 0 and vm._load(db)[2].get("words_try")                     # échec : noté, réessai plus tard, rien ne casse
    monkeypatch.setattr(voice, "transcribe", lambda d, audio, name, key="": {"language": "fra", "words": [[0.1, 0.4, "Re"]]})
    assert vm.ensure_words(db) == 0                                                          # pas avant 10 minutes
    items = vm._load(db)
    items[2]["words_try"] = 0
    vm._save(db, items)
    assert vm.ensure_words(db) == 1 and vm.listing(db)[2]["words"] == 1


def test_animations_calees_sur_le_fichier_et_coupes(monkeypatch):
    it = {"id": "c" * 12, "kind": "clip", "seconds": 20.0, "audio": True, "talk": [[1.0, 4.0], [6.0, 9.0]], "ext": ".mp4", "token": "t" * 32}
    raw = [{"type": "my_clip", "media": it["id"], "jumpcut": True, "layout": "split",
            "overlay": {"type": "kinetic", "lines": ["Titre"]}, "panels": [
        {"at": 1.2, "type": "badge", "lines": ["Opus 5.5"]}, {"at": 3.0, "type": "wave", "lines": ["Ta voix"]},
        {"at": 7.5, "type": "counter", "value": 0, "suffix": "€", "label": "gratuit"}, {"at": 15, "type": "chat", "lines": ["21"]},
        {"at": "?", "type": "badge", "lines": ["x"]}, {"at": 2, "type": "flow", "steps": ["une seule"]}]}]
    a, b = vs.build_spec("vertical", raw, [], media={it["id"]: it})["scenes"]
    assert a["layout"] == b["layout"] == "split"
    assert [p["at"] for p in a["panels"]] == [1.2, 3.0] and [p["at"] for p in b["panels"]] == [3.0, 7.5]   # b reprend l'onde en cours puis le compteur
    assert vs.build_spec("vertical", [a, b], [], media={it["id"]: it})["scenes"] == [a, b]                 # aller-retour stable
    monkeypatch.setattr(vm, "_load", lambda d: [dict(it)])
    monkeypatch.setattr(vm, "_save", lambda d, items: None)
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    ea, eb = vm.to_engine(object(), {"format": "vertical", "theme": "unic", "scenes": [a, b]})["scenes"]
    assert [[p[0], p[1], p[2]["type"]] for p in ea["panels"]] == [[0, 0, "kinetic"], [0.2, 0.0, "badge"], [2.0, 0.0, "wave"]]   # texte d'ouverture d'abord
    assert [[p[0], p[1], p[2]["type"]] for p in eb["panels"]] == [[0.0, 3.0, "wave"], [1.5, 0.0, "counter"]]   # l'onde continue (avance 3 s), le compteur à 1,5 s
    assert eb["layout"] == "split" and "at" not in eb["panels"][1][2]
    assert vs._readable({"type": "chat", "lines": ["21"]}) > 2 and vs._readable({"type": "flow", "steps": ["A", "B", "C"]}) > 2


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
@pytest.mark.parametrize("bpm", [120, 90])
def test_rythme_de_la_musique(tmp_path, bpm):
    p = 60 / bpm
    _sound(tmp_path / "m.wav", ["-f", "lavfi", "-i", f"aevalsrc='0.8*sin(2*PI*900*t)*exp(-40*mod(t-0.13,{p}))*gte(mod(t-0.13,{p}),0)+0.02*sin(2*PI*110*t)':d=20:s=44100"])
    got, beats = vm.detect_beats(tmp_path / "m.wav")
    assert abs(got - bpm) <= 2
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert len(beats) >= 20 / p - 3 and all(abs(g - p) < 0.05 for g in gaps)
    assert all(abs(((b - 0.13) / p) - round((b - 0.13) / p)) * p < 0.04 for b in beats)        # calés sur les coups
    assert vm.beats_from_onsets([0.0] * 10, 43) == (0.0, [])


def test_coupes_sur_les_temps_forts():
    beats = [round(0.26 + 0.5 * k, 2) for k in range(200)]
    music = {"id": "m" * 12, "kind": "music", "seconds": 100.0, "beats": beats, "bpm": 120.0}
    clip = {"id": "c" * 12, "kind": "clip", "seconds": 20.0, "audio": True}
    raw = [{"type": "kinetic", "lines": ["UNE PHRASE"], "seconds": 3.0}, {"type": "my_clip", "media": clip["id"], "start": 2, "seconds": 2.9},
           {"type": "my_clip", "media": clip["id"], "start": 8, "seconds": 3.0, "sound": True}, {"type": "title", "l1": "FIN", "seconds": 4.0}]
    media = {music["id"]: music, clip["id"]: clip}
    spec = vs.build_spec("vertical", raw, [], media=media, audio={"music": music["id"], "music_start": 1.0})
    assert spec["audio"]["beat"] is True
    secs = [s["seconds"] for s in spec["scenes"]]
    ends = [round(sum(secs[:i + 1]), 2) for i in range(len(secs))]
    assert any(abs(1.0 + ends[0] - b) < 0.06 for b in beats) and any(abs(1.0 + ends[1] - b) < 0.06 for b in beats)   # coupes sur un temps fort
    assert secs[2] == 3.0                                                                              # film parlé : jamais raccourci ni allongé
    assert all(abs(a - b) <= 0.45 for a, b in zip(secs, [3.0, 2.9, 3.0, 4.0]))                        # glissements courts
    assert vs.build_spec("vertical", spec["scenes"], [], media=media, audio=spec["audio"]) == spec     # aller-retour stable
    off = vs.build_spec("vertical", raw, [], media=media, audio={"music": music["id"], "music_start": 1.0, "beat": False})
    assert off["audio"]["beat"] is False and [s["seconds"] for s in off["scenes"]] == [3.0, 2.9, 3.0, 4.0]
    plain = {**music, "beats": []}
    assert "beat" not in vs.build_spec("vertical", raw, [], media={**media, music["id"]: plain}, audio={"music": music["id"]})["audio"]


def test_animation_lottie_du_patron(db, monkeypatch):
    lot = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "lottie" / "check.json").read_bytes()
    a = asyncio.run(vm.add(db, _Up("validé.json", lot), "lottie"))
    assert a["kind"] == "lottie" and a["seconds"] == 1.5
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.json", b'{"pas": "lottie"}'), "lottie"))
    assert "animation " + a["id"] in vm.catalog_text(db) and "« validé »" in vm.catalog_text(db)
    assert set(vs.BUILTIN_LOTTIE) == {"check", "spark", "arrow", "pin", "pulse"}
    clip = {"id": "c" * 12, "kind": "clip", "seconds": 10.0, "audio": True, "ext": ".mp4", "token": "t" * 32}
    media = {**vm.items_by_id(db), clip["id"]: clip}
    raw = [{"type": "lottie", "media": a["id"], "lines": ["Devis validé"]}, {"type": "lottie", "anim": "pin", "loop": True},
           {"type": "lottie", "media": "000000000000"},                                                           # inconnue : écartée
           {"type": "my_clip", "media": clip["id"], "seconds": 4, "layout": "split", "panels": [{"at": 1, "type": "lottie", "media": a["id"]}, {"at": 2, "type": "lottie", "anim": "spark"}]}]
    spec = vs.build_spec("vertical", raw, [], media=media)
    s0, s1, s2 = spec["scenes"]
    assert s0["media"] == a["id"] and s1["anim"] == "pin" and s1["loop"] is True and [p.get("media") or p.get("anim") for p in s2["panels"]] == [a["id"], "spark"]
    assert vs.build_spec("vertical", spec["scenes"], [], media=media)["scenes"] == spec["scenes"]
    items = vm._load(db) + [clip]
    monkeypatch.setattr(vm, "_load", lambda d: items)
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    e0, e1, e2 = vm.to_engine(db, spec)["scenes"]
    assert e0["url"].startswith("https://unic.example.com/api/public/video-media/") and "media" not in e0 and e1["anim"] == "pin"
    assert e2["panels"][0][2]["url"] == e0["url"] and e2["panels"][1][2]["anim"] == "spark"                    # même lien secret, ouvert pour la fabrication
    assert vm.media_type(pathlib.Path("x.json")) == "application/json"


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_depose_tout_ici_photos_et_type_reconnu(db, tmp_path, monkeypatch):
    from PIL import Image
    from app import vision
    buf = io.BytesIO()
    img = Image.new("RGB", (4000, 3000), (200, 120, 40))
    exif = img.getexif()
    exif[0x0112] = 6                                                                                   # photo prise en portrait (à tourner)
    exif[0x8825] = {2: (14.0, 41.0, 0.0)}                                                              # position GPS du téléphone
    img.save(buf, "JPEG", exif=exif)
    monkeypatch.setattr(vision, "disponible", lambda: True)
    monkeypatch.setattr(vision, "describe_frames", lambda frames: "#0 : Plafond BA13 fini dans un salon\nRésumé : Salon au plafond BA13 terminé.")
    p = asyncio.run(vm.add(db, _Up("IMG_2031.JPG", buf.getvalue()), "auto"))
    assert p["kind"] == "photo" and p["dims"] == [1920, 2560] and p["summary"] == "Salon au plafond BA13 terminé."   # tournée, réduite
    saved = Image.open(vm._dir() / f"{p['id']}.jpg")
    assert not saved.getexif().get(0x8825) and not saved.getexif().get(0x0112)                        # plus de position GPS
    assert vm.frame_path(db, p["id"], 0).read_bytes()[:2] == b"\xff\xd8"
    assert "photo " + p["id"] in vm.catalog_text(db) and "Salon au plafond BA13" in vm.catalog_text(db)
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.heic", b"....ftypheic"), "auto"))                               # format non reconnu
    with pytest.raises(vm.MediaError):
        asyncio.run(vm.add(db, _Up("x.jpg", b"pas une image"), "auto"))
    voice = _sound(tmp_path / "v.wav", ["-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*220*t)*lt(mod(t,1.4),1.0)':d=8:s=44100"])
    music = _sound(tmp_path / "m.wav", ["-f", "lavfi", "-i", "sine=f=330:d=8"])
    clip = _sound(tmp_path / "c.mp4", ["-f", "lavfi", "-i", "testsrc=d=3:s=320x240:r=25", "-pix_fmt", "yuv420p"])
    assert asyncio.run(vm.add(db, _Up("enregistrement.wav", voice), "auto"))["kind"] == "voice"        # des pauses : une voix
    m = asyncio.run(vm.add(db, _Up("fond.wav", music), "auto"))
    assert m["kind"] == "music" and asyncio.run(vm.add(db, _Up("Voix ElevenLabs.wav", music), "auto"))["kind"] == "voice"   # le nom compte
    assert asyncio.run(vm.add(db, _Up("chantier.MP4", clip), "auto"))["kind"] == "clip"
    v = vm.set_kind(db, m["id"], "voice")
    assert v["kind"] == "voice" and "phrases" in v and vm.set_kind(db, m["id"], "music")["kind"] == "music"
    with pytest.raises(vm.MediaError):
        vm.set_kind(db, p["id"], "music")                                                              # une photo ne devient pas un son
    spec = vs.build_spec("vertical", [{"type": "my_photo", "media": p["id"], "caption": "Salon fini", "seconds": 4},
                                      {"type": "my_photo", "media": m["id"]}], [], media=vm.items_by_id(db))
    assert spec["scenes"] == [{"type": "my_photo", "media": p["id"], "seconds": 4.0, "caption": "Salon fini"}]   # un son n'est pas une photo
    monkeypatch.setattr(vm.settings, "unic_public_url", "https://unic.example.com")
    e = vm.to_engine(db, spec)["scenes"][0]
    assert e["type"] == "photo" and e["url"].startswith("https://unic.example.com/api/public/video-media/") and e["direction"] == "in"


def test_l_ia_ne_met_que_ce_que_le_patron_donne_ou_demande(monkeypatch):
    from app import higgsfield
    seen = {}
    story = {"scenes": [{"type": "title", "l1": "CHANTIER"}, {"type": "stats", "facts": ["chantiers"], "items": [{"value": 3, "label": "Pièces"}, {"value": 2, "label": "Jours"}]},
                        {"type": "quote", "quote": "avis_khadige"}, {"type": "photo", "image": "hero-01.webp"}, {"type": "outro", "brand": True}]}
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(vs, "images", lambda db=None: ["hero-01.webp", "hero-02.webp"])
    monkeypatch.setattr(higgsfield, "status", lambda d: {"connected": False})
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: seen.update(user=user) or json.loads(json.dumps(story)))
    p = vs.plan(None, "Une vidéo sur la rénovation de ma cuisine avec mes photos", "vertical")
    assert [s["type"] for s in p["spec"]["scenes"]] == ["title", "stats"]                                  # ni avis, ni photo du site, ni carte de marque
    assert p["spec"]["scenes"][1]["items"] == [{"value": 3, "suffix": "", "label": "Pièces"}, {"value": 2, "suffix": "", "label": "Jours"}]   # ses chiffres, pas ceux de l'entreprise
    assert "Chiffres vrais" not in seen["user"] and "Photos (noms exacts)" not in seen["user"] and "+221" not in json.dumps(p["spec"])
    p = vs.plan(None, "Pub avec 2 photos du site, mes chiffres et mon téléphone à la fin", "vertical")
    assert [s["type"] for s in p["spec"]["scenes"]] == ["title", "stats", "quote", "photo", "outro"] and vs.FACTS["phone"] in p["spec"]["scenes"][-1]["lines"]
    assert "Chiffres vrais" in seen["user"] and "Photos (noms exacts)" in seen["user"]                     # demandé : permis
    assert vm.frame_times(200) == [round((i + 0.5) * 200 / 24, 1) for i in range(24)] and len(vm.frame_times(60)) == 12   # une longue vidéo : regardée de plus près
