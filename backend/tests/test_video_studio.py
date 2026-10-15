import io
import zipfile

import pytest

from app import repair, video_studio as vs


def test_scenario_standard_sans_cle(monkeypatch):
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "")
    p = vs.plan("")
    assert [c["key"] for c in p["spec"]["chapters"]] == list(vs.CATALOG["portfolio"]["chapters"])
    assert p["spec"]["url"] == "https://www.unicplaquiste.com/portfolio/" and 35 <= p["seconds"] <= 60


def test_l_ia_ne_choisit_ni_adresse_ni_selecteur():
    spec = vs.build_spec("portfolio", [
        {"key": "avis", "label": "<b>Avis</b>\x00 clients", "seconds": 99},
        {"key": "http://evil.example", "label": "x", "seconds": 5},      # hors catalogue : ignoré
        {"key": "avis", "label": "doublon", "seconds": 5},               # doublon : ignoré
        {"key": "contact", "label": "Contact", "seconds": "abc"}])       # durée absurde : valeur par défaut
    assert [c["key"] for c in spec["chapters"]] == ["avis", "contact"]
    assert spec["chapters"][0]["seconds"] == 9.0 and spec["chapters"][1]["seconds"] == 4.0
    assert "<" not in spec["chapters"][0]["label"] and "\x00" not in spec["chapters"][0]["label"]
    assert all(c["selector"].startswith("#") for c in spec["chapters"])
    assert vs.FACTS["phone"] in spec["end"] and spec["end"][-1] == "unicplaquiste.com"


def test_aucun_chapitre_valide_refuse():
    with pytest.raises(ValueError):
        vs.build_spec("portfolio", [{"key": "nimporte"}])


def test_start_reconstruit_le_scenario(monkeypatch):
    sent = {}
    monkeypatch.setattr(repair, "_ctx", lambda db: ("tok", "o/r", "main"))

    class R:
        status_code = 204
    monkeypatch.setattr(repair, "_gh", lambda m, path, tok, **kw: (sent.update(path=path, json=kw["json"]) or R()))
    out = vs.start(None, {"url": "https://evil.example/", "chapters": [{"key": "services", "label": "S", "seconds": 5}], "subtitle": "x", "end": ["a", "b", "c", "Appelle-moi", "e", "f"]})
    assert out["ok"] and sent["path"].endswith("/video.yml/dispatches")
    import json
    got = json.loads(sent["json"]["inputs"]["spec"])
    assert got["url"] == "https://www.unicplaquiste.com/portfolio/" and got["chapters"][0]["selector"] == "#services" and got["end"][3] == "Appelle-moi"


def _zip(name, data):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, data)
    return b.getvalue()


def test_zip_video_valide_et_refus(tmp_path, monkeypatch):
    from app.database import SessionLocal
    monkeypatch.setattr(vs.settings, "unic_data_dir", str(tmp_path))
    with SessionLocal() as db:
        ok = vs.save_zip(db, _zip("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 50), 7, None)
        assert ok["filename"].endswith(".mp4") and (tmp_path / "videos" / "portfolio-7.mp4").exists()
        for bad in (_zip("v.mp4", b"pas une video"), _zip("../v.mp4", b"\x00\x00\x00\x18ftypmp42"), b"pas un zip"):
            with pytest.raises(repair.RepairError):
                vs.save_zip(db, bad, 8, None)


def test_routes_protegees(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(vs.settings, "unic_access_code", "s3cret-code")
    main.ratelimit._mem.clear()
    with TestClient(main.app) as c:
        assert c.post("/api/website/video/plan", json={"brief": ""}).status_code == 401
        assert c.get("/api/website/video/status").status_code == 401
        assert c.post("/api/website/video/fetch").status_code == 401
        r = c.post("/api/website/video/plan", json={"brief": ""}, headers={"x-access-code": "s3cret-code"})
        assert r.status_code == 200 and r.json()["spec"]["chapters"]
