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
    assert hf.status(db)["video_left_today"] == 0


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
    state[hf.VIDEO_COUNT_KEY] = f"{date.today().isoformat()}:1"
    with pytest.raises(hf.HiggsfieldError, match="par jour") as exc:
        hf.start_video(db, "Un autre clip vidéo", 5, "square", False, "owner-1")
    assert exc.value.status == 429
    assert len(calls) == 1


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
