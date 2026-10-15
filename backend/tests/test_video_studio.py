import io
import json
import zipfile

import pytest

from app import repair, video_studio as vs


NAMES = ["ref-dakar-arena.webp", "realis-01-plafond.webp", "realis-02-cloisons.webp"]


def test_scenario_standard_sans_cle(monkeypatch):
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "")
    p = vs.plan(None, "", "horizontal")
    types = [s["type"] for s in p["spec"]["scenes"]]
    assert types[0] == "title" and types[-1] == "outro" and "page" in types and p["spec"]["format"] == "horizontal" and 20 <= p["seconds"] <= 60


def test_toutes_les_scenes_et_les_garde_fous():
    spec = vs.build_spec("square", [
        {"type": "title", "l1": "<b>Faux</b>\x00 plafonds", "seconds": 99},
        {"type": "photo", "image": "ref-dakar-arena.webp", "caption": "Dakar Arena"},
        {"type": "photo", "image": "http://evil.example/x.webp"},                 # hors catalogue : écartée
        {"type": "gallery", "images": ["realis-01-plafond.webp", "pirate.webp", "realis-02-cloisons.webp"]},
        {"type": "gallery", "images": ["realis-01-plafond.webp"]},               # une seule image valide : écartée
        {"type": "stats", "facts": ["chantiers", "inconnu", "satisfaits"]},
        {"type": "stats", "facts": ["inconnu", "autre"]},                         # aucun chiffre vrai : écartée
        {"type": "quote", "quote": "avis_khadige"}, {"type": "quote", "quote": "avis_invente"},
        {"type": "text", "heading": "Services", "bullets": ["Plafonds", "", "Cloisons"]},
        {"type": "page", "page": "portfolio", "chapters": [{"key": "avis", "label": "Avis", "seconds": 99}, {"key": "x"}]},
        {"type": "inconnu"}], NAMES)
    t = [s["type"] for s in spec["scenes"]]
    assert t == ["title", "photo", "gallery", "stats", "quote", "text", "page", "outro"]      # outro ajouté
    assert spec["scenes"][0]["seconds"] == 6 and "<" not in spec["scenes"][0]["l1"] and "\x00" not in spec["scenes"][0]["l1"]
    assert spec["scenes"][2]["images"] == ["realis-01-plafond.webp", "realis-02-cloisons.webp"]
    assert [i["value"] for i in spec["scenes"][3]["items"]] == [180, 98]
    assert spec["scenes"][4]["author"].startswith("Khadige") and spec["scenes"][5]["bullets"] == ["Plafonds", "Cloisons"]
    page = spec["scenes"][6]
    assert page["url"] == "https://www.unicplaquiste.com/portfolio/" and page["chapters"] == [{"key": "avis", "selector": "#avis", "label": "Avis", "seconds": 9.0}]
    assert vs.FACTS["phone"] in spec["scenes"][7]["lines"] and spec["format"] == "square"
    assert vs.build_spec("n'importe quoi", [{"type": "outro"}], NAMES)["format"] == "vertical"


def test_le_moteur_accepte_ce_que_le_serveur_produit():
    """Le contrat entre video_studio (serveur) et scripts/video/spec.py (moteur) : tout scénario valide côté serveur est accepté par le moteur."""
    import importlib.util, pathlib
    sp_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    m = importlib.util.spec_from_file_location("video_spec", sp_path); eng = importlib.util.module_from_spec(m); m.loader.exec_module(eng)
    spec = vs.build_spec("horizontal", [{"type": "title", "l1": "A"}, {"type": "photo", "image": "ref-dakar-arena.webp"}, {"type": "gallery", "images": NAMES[:2]},
                                         {"type": "stats", "facts": ["annees", "devis"]}, {"type": "quote", "quote": "avis_khadige"}, {"type": "text", "bullets": ["x"]},
                                         {"type": "page"}, {"type": "outro"}], NAMES)
    out = eng.clean(spec)
    assert [s["type"] for s in out["scenes"]] == [s["type"] for s in spec["scenes"]] and out["format"] == "horizontal"
    assert out["fps"] == 60 and eng.clean({**spec, "fps": 30})["fps"] == 30 and eng.clean({**spec, "fps": 7})["fps"] == 60   # fluidité par défaut : 60 i/s
    for bad in ({"scenes": [{"type": "photo", "image": "../../etc/passwd"}]}, {"scenes": [{"type": "page", "url": "https://evil.example/", "chapters": [{"selector": "#a"}]}]},
                {"scenes": [{"type": "page", "url": "https://www.unicplaquiste.com/", "chapters": [{"selector": "body > script"}]}]}):
        try:
            eng.clean(bad)
        except ValueError:
            continue
        raise AssertionError("le moteur aurait dû refuser")


def test_limites_video_elargies_et_refus_sans_troncature():
    from pydantic import ValidationError
    from app.api_website import VideoPlanIn

    assert len(VideoPlanIn(brief="x" * 20_000).brief) == 20_000
    with pytest.raises(ValidationError):
        VideoPlanIn(brief="x" * 20_001)

    scenes = [{"type": "title", "l1": f"Scène {i}", "seconds": 2.5} for i in range(19)]
    scenes.append({"type": "outro", "seconds": 5})
    spec = vs.build_spec("vertical", scenes, NAMES)
    assert len(spec["scenes"]) == 20
    assert vs._duration(spec) <= 600

    at_limit = [{"type": "text", "heading": "Services", "bullets": ["UniC"], "seconds": 10} for _ in range(59)]
    at_limit.append({"type": "text", "heading": "Services", "bullets": ["UniC"], "seconds": 5})
    at_limit.append({"type": "outro", "seconds": 5})
    spec_at_limit = vs.build_spec("vertical", at_limit, NAMES)
    assert vs._duration(spec_at_limit) == 600

    import importlib.util, pathlib
    sp_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    m = importlib.util.spec_from_file_location("video_spec_limit", sp_path)
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    assert sum(s["seconds"] for s in eng.clean(spec_at_limit)["scenes"]) == 600

    over_limit = [{"type": "text", "heading": "Services", "bullets": ["UniC"], "seconds": 10} for _ in range(60)]
    over_limit.append({"type": "outro", "seconds": 5})
    with pytest.raises(ValueError, match="10 minutes"):
        vs.build_spec("vertical", over_limit, NAMES)
    with pytest.raises(ValueError, match="10 minutes"):
        eng.clean(spec_at_limit | {"scenes": over_limit})

    too_many = [{"type": "title", "l1": f"Scène {i}", "seconds": 2.5} for i in range(201)]
    with pytest.raises(ValueError, match="200 scènes"):
        vs.build_spec("vertical", too_many, NAMES)

    # Vingt-cinq pages complètes dépassent le plafond de dix minutes.
    too_long = [{"type": "page", "page": "portfolio"} for _ in range(25)]
    with pytest.raises(ValueError, match="10 minutes"):
        vs.build_spec("vertical", too_long, NAMES)


def test_start_reconstruit_le_scenario(monkeypatch):
    sent = {}
    monkeypatch.setattr(repair, "_ctx", lambda db: ("tok", "o/r", "main"))
    monkeypatch.setattr(vs, "images", lambda db=None: NAMES)

    class R:
        status_code = 204
    monkeypatch.setattr(repair, "_gh", lambda m, path, tok, **kw: (sent.update(path=path, json=kw["json"]) or R()))
    out = vs.start(None, {"format": "horizontal", "scenes": [{"type": "photo", "image": "ref-dakar-arena.webp", "caption": "x"},
                                                              {"type": "page", "url": "https://evil.example/", "chapters": [{"key": "services", "selector": "body", "seconds": 5}]},
                                                              {"type": "outro", "cta": "Appelle-moi", "lines": ["faux"]}]})
    assert out["ok"] and sent["path"].endswith("/video.yml/dispatches")
    got = json.loads(sent["json"]["inputs"]["spec"])
    assert got["format"] == "horizontal" and got["scenes"][1]["url"] == "https://www.unicplaquiste.com/portfolio/" and got["scenes"][1]["chapters"][0]["selector"] == "#services"
    assert got["scenes"][2]["lines"][3] == "Appelle-moi" and "faux" not in got["scenes"][2]["lines"]
    with pytest.raises(repair.RepairError):
        vs.start(None, {"scenes": [{"type": "photo", "image": "inconnue.webp"}, {"type": "inconnu"}]})


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
        assert ok["filename"].endswith(".mp4") and (tmp_path / "videos" / "video-7.mp4").exists()
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
        assert c.post("/api/website/video/ai/start", json={"prompt": "Un clip vidéo test", "duration": 5, "format": "vertical"}).status_code == 401
        assert c.get("/api/website/video/ai/status").status_code == 401
        r = c.post("/api/website/video/plan", json={"brief": ""}, headers={"x-access-code": "s3cret-code"})
        assert r.status_code == 200 and r.json()["spec"]["scenes"]
