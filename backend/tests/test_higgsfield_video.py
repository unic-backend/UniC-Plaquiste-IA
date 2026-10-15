import json
from datetime import date
from types import SimpleNamespace

import pytest

from app import higgsfield as hf


class FakeDB:
    def commit(self):
        pass


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def setup_state(monkeypatch):
    state = {}
    monkeypatch.setattr(hf, "_get", lambda db, key: state.get(key, ""))
    monkeypatch.setattr(hf, "_put", lambda db, key, value: state.__setitem__(key, value))
    monkeypatch.setattr(hf, "credentials", lambda db: ("key-id", "key-secret"))
    return state, FakeDB()


def test_video_start_uses_official_model_and_limits_cost(monkeypatch):
    state, db = setup_state(monkeypatch)
    sent = {}

    def fake_http(method, url, creds, **kwargs):
        sent.update(method=method, url=url, creds=creds, kwargs=kwargs)
        return Response(200, {"request_id": "request_12345678"})

    monkeypatch.setattr(hf, "_http", fake_http)
    out = hf.start_video(db, "Un salon moderne avec faux plafond BA13", 10, "vertical", True, "owner-1")

    assert out["state"] == "queued"
    assert out["duration"] == 10 and out["format"] == "vertical"
    assert "request_id" not in out
    assert sent["url"] == f"{hf.API}{hf.VIDEO_PATH}"
    assert sent["kwargs"]["json"] == {
        "prompt": "Un salon moderne avec faux plafond BA13",
        "duration": 10,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "enable_thinking": False,
    }
    assert sent["kwargs"]["headers"]["Idempotency-Key"]
    assert json.loads(state[hf.VIDEO_JOB_KEY])["user_id"] == "owner-1"
    assert hf.status(db)["video_left_today"] == hf.MAX_VIDEO_PER_DAY - 1


def test_video_start_refuse_doublon_et_quota(monkeypatch):
    state, db = setup_state(monkeypatch)
    calls = []
    monkeypatch.setattr(hf, "_http", lambda *a, **kw: (calls.append(a) or Response(200, {"request_id": "request_12345678"})))
    hf.start_video(db, "Un salon moderne avec faux plafond BA13", 5, "square", False, "owner-1")

    with pytest.raises(hf.HiggsfieldError, match="déjà en cours") as exc:
        hf.start_video(db, "Un deuxième clip vidéo", 5, "square", False, "owner-1")
    assert exc.value.status == 409
    assert len(calls) == 1

    state[hf.VIDEO_JOB_KEY] = ""
    state[hf.VIDEO_COUNT_KEY] = f"{date.today().isoformat()}:{hf.MAX_VIDEO_PER_DAY}"
    with pytest.raises(hf.HiggsfieldError, match="par jour") as exc:
        hf.start_video(db, "Un autre clip vidéo", 5, "square", False, "owner-1")
    assert exc.value.status == 429
    assert len(calls) == 1


def test_video_long_reserve_les_clips_et_demarre_sans_depassement(monkeypatch, tmp_path):
    state, db = setup_state(monkeypatch)
    sent = []
    monkeypatch.setattr(hf.settings, "unic_data_dir", str(tmp_path))
    monkeypatch.setattr(hf, "_http", lambda method, url, creds, **kw:
                        (sent.append((method, url, kw)) or Response(200, {"request_id": "request_12345678"})))

    out = hf.start_long_video(
        db,
        ["Un salon contemporain avec faux plafond BA13", "Gros plan sur les finitions lumineuses"],
        60, "horizontal", True, "owner-1",
    )
    assert out["kind"] == "long"
    assert out["state"] == "queued"
    assert out["total_clips"] == 2
    assert out["target_seconds"] == 60
    assert len(sent) == 1  # un seul clip est soumis à la fois
    assert sent[0][2]["json"]["duration"] == 30
    assert state[hf.VIDEO_COUNT_KEY] == f"{date.today().isoformat()}:2"


def test_video_long_refuse_un_nombre_de_consignes_incoherent(monkeypatch):
    _, db = setup_state(monkeypatch)
    with pytest.raises(hf.HiggsfieldError, match="exactement 2 consignes"):
        hf.start_long_video(db, ["Une consigne valide"], 60, "vertical", False, "owner-1")


def test_video_start_valide_duree_format_et_connexion(monkeypatch):
    state, db = setup_state(monkeypatch)
    calls = []
    monkeypatch.setattr(hf, "_http", lambda *a, **kw: (calls.append(a) or Response(200, {"request_id": "request_12345678"})))

    with pytest.raises(hf.HiggsfieldError, match="2 et 30"):
        hf.start_video(db, "Un clip valide pour tester", 31, "vertical", True, "owner-1")
    with pytest.raises(hf.HiggsfieldError, match="Format invalide"):
        hf.start_video(db, "Un clip valide pour tester", 5, "panoramique", True, "owner-1")
    assert not calls

    monkeypatch.setattr(hf, "credentials", lambda db: ("", ""))
    with pytest.raises(hf.HiggsfieldError, match="pas connecté"):
        hf.start_video(db, "Un clip valide pour tester", 5, "vertical", True, "owner-1")
    assert not calls


def test_erreur_cle_higgsfield_ne_ressemble_pas_a_une_session_app_expiree(monkeypatch):
    state, db = setup_state(monkeypatch)
    monkeypatch.setattr(hf, "_http", lambda *a, **kw: Response(401, {"error": "unauthorized"}))
    with pytest.raises(hf.HiggsfieldError) as exc:
        hf.start_video(db, "Un clip vidéo pour tester", 5, "vertical", True, "owner-1")
    assert exc.value.status == 400
    assert "Clés Higgsfield refusées" in str(exc.value)
    assert hf.status(db)["video_left_today"] == hf.MAX_VIDEO_PER_DAY


def test_video_status_verifie_proprietaire_et_recupere_mp4(monkeypatch, tmp_path):
    state, db = setup_state(monkeypatch)
    state[hf.VIDEO_JOB_KEY] = json.dumps({
        "state": "queued", "user_id": "owner-1", "request_id": "request_12345678",
        "duration": 5, "format": "horizontal", "created_at": 1,
    })
    with pytest.raises(hf.HiggsfieldError) as exc:
        hf.video_status(db, "autre-utilisateur")
    assert exc.value.status == 403

    monkeypatch.setattr(hf, "_http", lambda *a, **kw: Response(200, {
        "status": "completed", "video": {"url": "https://cdn.example/clip.mp4"}
    }))
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"x" * 64
    monkeypatch.setattr(hf, "_download_video", lambda url: mp4)
    monkeypatch.setattr(hf.settings, "unic_data_dir", str(tmp_path))
    monkeypatch.setattr(hf, "new_id", lambda: "abcdef12-3456-7890")
    monkeypatch.setattr(hf, "store_artifact", lambda db, path, filename, entity_type, entity_id, key, user_id, mime:
                        SimpleNamespace(id="artifact-1", filename=filename, size=path.stat().st_size))

    out = hf.video_status(db, "owner-1")
    assert out["state"] == "ready"
    assert out["artifact"]["id"] == "artifact-1"
    assert out["artifact"]["url"] == "/api/artifacts/artifact-1/download"
    saved = tmp_path / "storage" / "artifacts" / "generated" / "clip_ia_abcdef12.mp4"
    assert saved.read_bytes() == mp4
    assert json.loads(state[hf.VIDEO_JOB_KEY])["state"] == "ready"


def test_video_status_garde_en_cours_si_higgsfield_traite(monkeypatch):
    state, db = setup_state(monkeypatch)
    state[hf.VIDEO_JOB_KEY] = json.dumps({
        "state": "queued", "user_id": "owner-1", "request_id": "request_12345678",
        "duration": 5, "format": "vertical", "created_at": 1,
    })
    monkeypatch.setattr(hf, "_http", lambda *a, **kw: Response(200, {"status": "in_progress"}))
    out = hf.video_status(db, "owner-1")
    assert out["state"] == "processing"
    assert "génère" in out["detail"]


def _assembly_setup(monkeypatch, tmp_path, concat):
    import time as _t
    state, db = setup_state(monkeypatch)
    monkeypatch.setattr(hf.settings, "unic_data_dir", str(tmp_path))
    monkeypatch.setattr(hf, "new_id", lambda: "abcdef12-3456-7890")
    monkeypatch.setattr(hf, "store_artifact", lambda db, path, filename, entity_type, entity_id, key, user_id, mime:
                        SimpleNamespace(id="artifact-9", filename=filename, size=path.stat().st_size))
    monkeypatch.setattr(hf, "_concat", concat)
    folder = tmp_path / "work"
    folder.mkdir()
    clips = []
    for i in (1, 2):
        c = folder / f"clip_{i:02d}.mp4"
        c.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 32)
        clips.append(str(c))
    state[hf.VIDEO_JOB_KEY] = json.dumps({"kind": "long", "state": "assembling", "user_id": "owner-1", "format": "vertical", "target_seconds": 60,
                                          "scenes": [{"prompt": "a" * 10, "duration": 30}] * 2, "clip_paths": clips, "work_dir": str(folder), "current_index": 2})
    return state, db, folder, clips, _t


def _wait(state, _t, want):
    for _ in range(200):
        if json.loads(state[hf.VIDEO_JOB_KEY])["state"] in want:
            return json.loads(state[hf.VIDEO_JOB_KEY])
        _t.sleep(0.05)
    raise AssertionError("assemblage jamais terminé")


def test_assemblage_en_arriere_plan_ne_bloque_pas_et_le_document_survit(monkeypatch, tmp_path):
    import threading
    gate = threading.Event()

    def concat(paths, listing, output):
        gate.wait(5)                                   # ffmpeg « lent » : la requête ne doit PAS l'attendre
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 64)
    state, db, folder, clips, _t = _assembly_setup(monkeypatch, tmp_path, concat)
    t0 = _t.time()
    out = hf.video_status(db, "owner-1")
    assert out["state"] == "assembling" and _t.time() - t0 < 2          # retour immédiat
    assert hf.video_status(db, "owner-1")["state"] == "assembling"       # 2e appel : pas de 2e assemblage (verrou)
    assert threading.active_count() >= 1 and sum(t.name == "video-ia-assemblage" for t in threading.enumerate()) == 1
    gate.set()
    job = _wait(state, _t, ("ready", "failed"))
    assert job["state"] == "ready" and job["artifact"]["url"] == "/api/artifacts/artifact-9/download"
    saved = tmp_path / "storage" / "artifacts" / "generated" / "video_longue_abcdef12.mp4"
    assert saved.is_file() and saved.read_bytes().endswith(b"v" * 64)     # le fichier du document existe encore (l'ancien code le supprimait)
    assert not any(__import__("pathlib").Path(c).exists() for c in clips)


def test_assemblage_en_echec_garde_les_clips(monkeypatch, tmp_path):
    def concat(paths, listing, output):
        raise hf.HiggsfieldError("FFmpeg n'a pas réussi à assembler les clips.", 500)
    state, db, folder, clips, _t = _assembly_setup(monkeypatch, tmp_path, concat)
    hf.video_status(db, "owner-1")
    job = _wait(state, _t, ("ready", "failed"))
    assert job["state"] == "failed" and "clips sont conservés" in job["detail"]
    assert all(__import__("pathlib").Path(c).exists() for c in clips)


def test_verrou_perime_relance_et_clips_manquants_echouent(monkeypatch, tmp_path):
    import os
    def concat(paths, listing, output):
        output.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 8)
    state, db, folder, clips, _t = _assembly_setup(monkeypatch, tmp_path, concat)
    lock = folder / hf.ASSEMBLY_LOCK
    lock.write_text("")
    old = _t.time() - hf.ASSEMBLY_STALE_S - 10
    os.utime(lock, (old, old))
    hf.video_status(db, "owner-1")                                          # verrou périmé (serveur redémarré) : on relance
    assert _wait(state, _t, ("ready", "failed"))["state"] == "ready"
    (tmp_path / "b").mkdir()
    state2, db2, folder2, clips2, _ = _assembly_setup(monkeypatch, tmp_path / "b", concat)
    __import__("pathlib").Path(clips2[0]).unlink()                          # clip manquant : échec net, pas d'assemblage
    assert hf.video_status(db2, "owner-1")["state"] == "failed"


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg absent")
def test_concat_reel_avec_ffmpeg(tmp_path):
    """Vrai ffmpeg : deux clips de même format se collent sans ré-encodage ; des formats différents passent par le ré-encodage."""
    import subprocess
    def clip(name, size):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration=1",
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp_path / name)], check=True)
        return tmp_path / name
    def duration(path):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
        return float(r.stdout)
    same = [clip("a.mp4", "320x240"), clip("b.mp4", "320x240")]
    out = tmp_path / "out.mp4"
    hf._concat(same, tmp_path / "l.txt", out)
    assert 1.9 < duration(out) < 2.2
    mixed = [clip("c.mp4", "320x240"), clip("d.mp4", "160x120")]
    out2 = tmp_path / "out2.mp4"
    hf._concat(mixed, tmp_path / "l2.txt", out2)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=width,nb_read_frames", "-of", "csv=p=0", str(out2)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    assert probe[0] == "320" and 59 <= int(probe[1]) <= 62                       # formats différents : ré-encodé à la taille du premier, environ 2 × 30 images
    assert hf._stream_signature(same[0]) == hf._stream_signature(same[1]) != hf._stream_signature(mixed[1])
