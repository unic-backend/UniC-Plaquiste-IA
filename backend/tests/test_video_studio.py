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
    assert vs.FACTS["phone"] in p["spec"]["scenes"][-1]["lines"]            # sans consigne : présentation de l'entreprise


def test_un_sujet_quelconque_ne_donne_jamais_une_video_d_entreprise(monkeypatch):
    """« Un lion qui court après ses petits » : pas de clé Claude -> on le dit (on ne livre pas une vidéo de plaquiste) ; avec Claude -> scénario libre, sans téléphone."""
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "")
    with pytest.raises(repair.RepairError) as e:
        vs.plan(None, "Un lion qui court après ses petits dans la savane", "vertical")
    assert e.value.status == 400
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: {"theme": "earth", "scenes": [
        {"type": "title", "l1": "LA SAVANE", "l2": "LE LION", "sub": "Un instant de vie"},
        {"type": "stats", "items": [{"value": 80, "suffix": " km/h", "label": "Vitesse de pointe"}, {"value": 3, "suffix": "", "label": "Petits par portée"}]},
        {"type": "quote", "text": "Le plus fort n'est pas celui qui court le plus vite.", "author": "Proverbe"},
        {"type": "outro", "lines": ["Fin", "Merci d'avoir regardé"]}]})
    p = vs.plan(None, "Un lion qui court après ses petits dans la savane", "vertical")
    assert p["spec"]["theme"] == "earth" and [c["type"] for c in p["spec"]["scenes"]] == ["title", "stats", "quote", "outro"]
    assert "+221" not in json.dumps(p["spec"]) and "UNIC" not in json.dumps(p["spec"])      # rien de l'entreprise
    assert p["spec"]["scenes"][1]["items"][0] == {"value": 80, "suffix": " km/h", "label": "Vitesse de pointe"}
    assert p["spec"]["scenes"][2]["author"] == "Proverbe" and p["spec"]["scenes"][3]["lines"] == ["Fin", "Merci d'avoir regardé"]
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: {"scenes": [{"type": "inconnu"}]})
    with pytest.raises(repair.RepairError) as e:
        vs.plan(None, "Un lion", "vertical")
    assert e.value.status == 502                                              # scénario inutilisable : on le dit
    import importlib.util, pathlib
    m = importlib.util.spec_from_file_location("video_spec_th", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py")
    eng = importlib.util.module_from_spec(m); m.loader.exec_module(eng)
    assert eng.clean(p["spec"])["theme"] == "earth" and eng.clean({**p["spec"], "theme": "inconnu"})["theme"] == "unic"


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
    assert t == ["title", "photo", "gallery", "stats", "quote", "text", "page"]                  # plus d'outro imposé
    assert spec["scenes"][0]["seconds"] == 6 and "<" not in spec["scenes"][0]["l1"] and "\x00" not in spec["scenes"][0]["l1"]
    assert spec["scenes"][2]["images"] == ["realis-01-plafond.webp", "realis-02-cloisons.webp"]
    assert [i["value"] for i in spec["scenes"][3]["items"]] == [180, 98]
    assert spec["scenes"][4]["author"].startswith("Khadige") and spec["scenes"][5]["bullets"] == ["Plafonds", "Cloisons"]
    page = spec["scenes"][6]
    assert page["url"] == "https://www.unicplaquiste.com/portfolio/" and page["chapters"] == [{"key": "avis", "selector": "#avis", "label": "Avis", "seconds": 9.0}]
    assert spec["format"] == "square" and spec["theme"] == "unic"
    brand = vs.build_spec("vertical", [{"type": "outro", "brand": True, "cta": "Appelle-nous", "lines": ["faux"]}], NAMES)["scenes"][0]
    assert vs.FACTS["phone"] in brand["lines"] and "Appelle-nous" in brand["lines"] and "faux" not in brand["lines"]       # carte entreprise : faits du code
    assert vs.build_spec("n'importe quoi", [{"type": "outro"}], NAMES)["format"] == "vertical"
    assert vs.build_spec("vertical", [{"type": "outro"}], NAMES)["scenes"][0]["lines"] == ["Merci"]


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

    import importlib.util, pathlib
    sp_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    m = importlib.util.spec_from_file_location("video_spec_limit", sp_path)
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)

    # Aucun plafond de durée métier : 5 h 30 (2 000 scènes de 10 s) sont acceptées par le serveur ET par le moteur
    long_video = [{"type": "text", "heading": "Services", "bullets": ["UniC"], "seconds": 10} for _ in range(2000)]
    long_video.append({"type": "outro", "seconds": 5})
    spec_long = vs.build_spec("vertical", long_video, NAMES)
    assert vs._duration(spec_long) == 20005
    cleaned = eng.clean(spec_long)
    parts = eng.chunks(cleaned["scenes"], 90)
    assert 2 <= len(parts) <= 250 and [s for p in parts for s in p] == cleaned["scenes"]       # tronçons : tout est couvert, dans l'ordre, sans couper de scène
    assert all(p for p in parts)

    # Garde-fous techniques seulement (12 h, 5 000 scènes)
    with pytest.raises(ValueError, match="12 heures|heures"):
        vs.build_spec("vertical", [{"type": "text", "heading": "S", "bullets": ["U"], "seconds": 10} for _ in range(4400)], NAMES)
    with pytest.raises(ValueError, match="5000"):
        vs.build_spec("vertical", [{"type": "title", "l1": f"S{i}", "seconds": 2.5} for i in range(5001)], NAMES)
    with pytest.raises(ValueError, match="12 heures"):
        eng.clean({"format": "vertical", "scenes": [{"type": "text", "heading": "S", "bullets": ["U"], "seconds": 10}] * 4400})


def test_tronconsisation_et_transport():
    import importlib.util, pathlib
    m = importlib.util.spec_from_file_location("video_spec_chunks", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py")
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    sc = [{"type": "title", "seconds": 4.0, "l1": "A", "l2": "", "sub": ""}] * 10
    assert [len(p) for p in eng.chunks(sc, 12)] == [3, 3, 3, 1]           # jamais au milieu d'une scène
    assert len(eng.chunks(sc * 1000, 1, max_chunks=250)) <= 250            # limite des matrices GitHub : les tronçons grossissent
    page = {"type": "page", "seconds": 0, "hero_seconds": 4.4, "chapters": [{"selector": "#a", "label": "A", "seconds": 4}]}
    assert eng.scene_seconds(page) == 10.9
    # petit scénario : JSON brut ; gros scénario : « gz: » + base64, décodable
    small = vs.build_spec("vertical", [{"type": "title", "l1": "A"}], NAMES)
    assert vs._transport(small).startswith("{")
    big = vs.build_spec("vertical", [{"type": "text", "heading": f"Titre {i}", "bullets": [f"Puce numéro {i} " * 3], "seconds": 4} for i in range(900)], NAMES)
    t = vs._transport(big)
    import base64, gzip
    assert t.startswith("gz:") and len(t) <= vs.DISPATCH_INPUT_MAX and json.loads(gzip.decompress(base64.b64decode(t[3:]))) == big


def test_start_reconstruit_le_scenario(monkeypatch):
    sent = {}
    monkeypatch.setattr(repair, "_ctx", lambda db: ("tok", "o/r", "main"))
    monkeypatch.setattr(vs, "images", lambda db=None: NAMES)
    from app import video_hybrid
    monkeypatch.setattr(video_hybrid, "clear", lambda db: None)

    class R:
        status_code = 204
    monkeypatch.setattr(repair, "_gh", lambda m, path, tok, **kw: (sent.update(path=path, json=kw["json"]) or R()))
    out = vs.start(None, {"format": "horizontal", "scenes": [{"type": "photo", "image": "ref-dakar-arena.webp", "caption": "x"},
                                                              {"type": "page", "url": "https://evil.example/", "chapters": [{"key": "services", "selector": "body", "seconds": 5}]},
                                                              {"type": "outro", "brand": True, "cta": "Appelle-moi", "lines": ["faux"]}]})
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
