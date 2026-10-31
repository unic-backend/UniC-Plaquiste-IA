import json
import time
from types import SimpleNamespace

import pytest

from app import higgsfield as hf, repair, video_hybrid as vh, video_studio as vs

NAMES = ["ref-dakar-arena.webp"]


class FakeDB:
    def commit(self):
        pass

    def rollback(self):
        pass


class Resp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload or {}

    def json(self):
        return self._p


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Higgsfield simulé : un stockage clé/valeur, des quotas, un journal d'appels, des réponses programmables."""
    st = {"store": {}, "calls": [], "script": [], "dispatched": []}
    monkeypatch.setattr(hf, "_get", lambda db, k: st["store"].get(k, ""))
    monkeypatch.setattr(hf, "_put", lambda db, k, v: st["store"].__setitem__(k, v))
    monkeypatch.setattr(hf, "credentials", lambda db: ("kid", "sec"))
    monkeypatch.setattr(hf.settings, "unic_data_dir", str(tmp_path))
    monkeypatch.setattr(vh, "ensure_driver", lambda: None)          # les pas sont déroulés à la main (pas de fil)

    def http(method, url, creds, **kw):
        st["calls"].append((method, url.split("api.higgsfield.ai")[-1], kw.get("json")))
        return st["script"].pop(0)
    monkeypatch.setattr(hf, "_http", http)
    monkeypatch.setattr(vs, "dispatch", lambda db, spec: st["dispatched"].append(spec) or {"ok": True})
    return st


SPEC = {"format": "vertical", "theme": "earth", "scenes": [
    {"type": "title", "seconds": 3, "l1": "LE LION", "l2": "", "sub": ""},
    {"type": "ai_clip", "seconds": 8, "prompt": "Un lion court dans la savane, plan large, lumière dorée"},
    {"type": "text", "seconds": 4, "heading": "Le départ", "bullets": ["Un"]},
    {"type": "ai_image", "seconds": 4, "prompt": "Portrait d'un lionceau dans les hautes herbes", "caption": "Le petit", "direction": "left"}]}


def test_les_scenes_ia_ne_passent_que_si_autorisees_et_dans_les_quotas():
    raw = [{"type": "ai_clip", "seconds": 99, "prompt": "Un lion court dans la savane"}, {"type": "ai_clip", "prompt": "Deuxième clip refusé par le quota"},
           {"type": "ai_clip", "prompt": "court"}, {"type": "ai_image", "prompt": "Une image de lionceau"}, {"type": "title", "l1": "A"}]
    assert [s["type"] for s in vs.build_spec("vertical", raw, NAMES)["scenes"]] == ["title"]                           # sans autorisation : écartées
    spec = vs.build_spec("vertical", raw, NAMES, ai={"clips": 1, "images": 1})
    assert [s["type"] for s in spec["scenes"]] == ["ai_clip", "ai_image", "title"] and spec["scenes"][0]["seconds"] == 30
    assert vh.ai_counts(spec) == (1, 1)


def test_le_plan_offre_les_scenes_ia_si_activees_connectees_et_dans_le_plafond(monkeypatch):
    """Décision du patron (après #245) : scènes IA payantes réactivées, plafonnées par les quotas du jour, et coupables dans les réglages."""
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle")
    seen = {}

    def ask(system, user, tool):
        seen.update(system=system, user=user, types=tool["input_schema"]["properties"]["scenes"]["items"]["properties"]["type"]["enum"])
        return {"theme": "earth", "scenes": [{"type": "ai_clip", "seconds": 6, "prompt": "Un lion court dans la savane"}, {"type": "title", "l1": "LION"}]}
    monkeypatch.setattr(vs, "_ask", ask)
    monkeypatch.setattr(vs, "ai_enabled", lambda db: True)
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 3, "left_today": 2})
    p = vs.plan(FakeDB(), "Un lion qui court", "vertical")
    assert "ai_clip" in seen["types"] and "SCÈNES IA" in seen["system"] and "3 film(s) IA" in seen["user"] and p["ai"] == {"clips": 1, "images": 0}
    off = ({"connected": False}, {"connected": True, "video_left_today": 0, "left_today": 0})   # non connecté, plafond du jour atteint
    for st in off:
        monkeypatch.setattr(hf, "status", lambda db, st=st: st)
        p = vs.plan(FakeDB(), "Un lion qui court", "vertical")
        assert "ai_clip" not in seen["types"] and "SCÈNES IA" not in seen["system"] and p["ai"] == {"clips": 0, "images": 0}
        assert [s["type"] for s in p["spec"]["scenes"]] == ["title"]                       # une scène IA renvoyée quand même : écartée
    monkeypatch.setattr(vs, "ai_enabled", lambda db: False)                              # le patron a coupé les scènes IA
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 3, "left_today": 2})
    p = vs.plan(FakeDB(), "Un lion qui court", "vertical")
    assert "ai_clip" not in seen["types"] and p["ai"] == {"clips": 0, "images": 0}


def test_demarrage_refuse_hors_quota_ou_sans_connexion(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": False, "video_left_today": 0, "left_today": 0})
    with pytest.raises(vh.HybridError, match="pas connecté"):
        vh.start(FakeDB(), SPEC, "u1")
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 0, "left_today": 5})
    with pytest.raises(vh.HybridError) as e:
        vh.start(FakeDB(), SPEC, "u1")
    assert e.value.status == 429 and not world["calls"]            # aucun appel payant n'est parti


def test_chaine_complete_un_media_a_la_fois_puis_montage(monkeypatch, world):
    # état réel de higgsfield.status (quotas lus dans le stockage simulé) : les compteurs de crédits sont vérifiés pour de vrai
    out = vh.start(FakeDB(), SPEC, "u1")
    assert out["ai"] == {"clips": 1, "images": 1} and json.loads(world["store"][vh.KEY])["state"] == "assets"
    with pytest.raises(vh.HybridError, match="déjà en cours"):
        vh.start(FakeDB(), SPEC, "u1")
    db = FakeDB()
    world["script"] += [Resp(200, {"request_id": "clip-request-1"}), Resp(200, {"status": "in_progress"}),
                        Resp(200, {"status": "completed", "video": {"url": "https://cdn.example/lion.mp4"}}),
                        Resp(200, {"request_id": "img-request-1"}),
                        Resp(200, {"status": "completed", "images": [{"url": "https://cdn.example/cub.png"}]})]
    for _ in range(5):
        vh.step(db)
    assert [c[1].split("?")[0] for c in world["calls"]] == [hf.VIDEO_PATH, "/requests/clip-request-1/status", "/requests/clip-request-1/status", hf.IMAGE_PATH, "/requests/img-request-1/status"]
    assert world["calls"][0][2]["duration"] == 8 and world["calls"][0][2]["generate_audio"] is False and world["calls"][0][2]["aspect_ratio"] == "9:16"
    assert not world["dispatched"]                                  # tant que tout n'est pas prêt, rien ne part vers GitHub
    job = vh.step(db)                                                # tous les médias sont prêts : lancement du montage
    eng = world["dispatched"][0]
    assert job["state"] == "rendering" and [s["type"] for s in eng["scenes"]] == ["title", "clip", "text", "photo"]
    assert eng["scenes"][1] == {"type": "clip", "url": "https://cdn.example/lion.mp4", "seconds": 8}
    assert eng["scenes"][3]["url"] == "https://cdn.example/cub.png" and eng["scenes"][3]["caption"] == "Le petit" and eng["theme"] == "earth"
    assert world["store"][hf.VIDEO_COUNT_KEY].endswith(":1") and world["store"]["higgsfield_count"].endswith(":1")        # un crédit de chaque, pas plus
    pub = vh.public(db)
    assert pub["state"] == "rendering" and "url" not in json.dumps(pub) and "request" not in json.dumps(pub)               # rien du fournisseur côté interface
    vh.step(db)
    assert len(world["calls"]) == 5 and len(world["dispatched"]) == 1                                                     # job terminé : plus aucun appel


def test_un_echec_arrete_la_chaine_et_rend_le_credit_si_refus_net(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 5, "left_today": 5})
    vh.start(FakeDB(), SPEC, "u1")
    world["script"] += [Resp(400)]
    job = vh.step(FakeDB())
    assert job["state"] == "failed" and len(world["calls"]) == 1 and world["store"][hf.VIDEO_COUNT_KEY].endswith(":0")     # refus net : crédit rendu
    vh.step(FakeDB())
    assert len(world["calls"]) == 1                                                                                       # aucune relance automatique
    # échec chez le fournisseur en cours de route : la chaîne s'arrête, aucune image n'est commandée
    world["store"].pop(vh.KEY)
    vh.start(FakeDB(), SPEC, "u1")
    world["script"] += [Resp(200, {"request_id": "clip-request-2"}), Resp(200, {"status": "nsfw"})]
    vh.step(FakeDB()); job = vh.step(FakeDB())
    assert job["state"] == "failed" and "modération" in job["detail"] and not any(c[1] == hf.IMAGE_PATH for c in world["calls"])


def test_requete_ambigue_ne_rend_pas_le_credit_et_ne_relance_pas(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 5, "left_today": 5})
    vh.start(FakeDB(), SPEC, "u1")

    def boom(*a, **k):
        raise hf.HiggsfieldError("Higgsfield est injoignable", 502)
    monkeypatch.setattr(hf, "_http", boom)
    job = vh.step(FakeDB())
    assert job["state"] == "failed" and "historique" in job["detail"] and world["store"][hf.VIDEO_COUNT_KEY].endswith(":1")


def test_relancer_le_montage_sans_nouveau_credit(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 5, "left_today": 5})
    vh.start(FakeDB(), SPEC, "u1")
    world["script"] += [Resp(200, {"request_id": "clip-request-3"}), Resp(200, {"status": "completed", "video": {"url": "https://cdn.example/a.mp4"}}),
                        Resp(200, {"request_id": "img-request-3"}), Resp(200, {"status": "completed", "images": [{"url": "https://cdn.example/b.png"}]})]

    def refuse(db, spec):
        raise repair.RepairError("GitHub refuse", 403)
    monkeypatch.setattr(vs, "dispatch", refuse)
    for _ in range(5):
        job = vh.step(FakeDB())
    assert job["state"] == "failed" and job["can_retry"] is True and "sans nouveau crédit" in job["detail"]
    calls = len(world["calls"])
    monkeypatch.setattr(vs, "dispatch", lambda db, spec: world["dispatched"].append(spec) or {"ok": True})
    assert vs.retry_render(FakeDB())["ok"] is True and len(world["calls"]) == calls and world["dispatched"]
    with pytest.raises(repair.RepairError):
        vs.retry_render(FakeDB())                                    # plus rien à relancer


def test_adresse_de_media_douteuse_refusee(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 5, "left_today": 5})
    vh.start(FakeDB(), SPEC, "u1")
    world["script"] += [Resp(200, {"request_id": "clip-request-4"}), Resp(200, {"status": "completed", "video": {"url": "http://10.0.0.1/x.mp4"}})]
    vh.step(FakeDB()); job = vh.step(FakeDB())
    assert job["state"] == "failed" and "adresse" in job["detail"]


def test_verrou_du_fil_perime_est_repris(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(vh.settings, "unic_data_dir", str(tmp_path))
    assert vh._acquire() is True and vh._acquire() is False          # un seul fil à la fois
    old = time.time() - vh.LOCK_STALE_S - 5
    os.utime(vh._lock_path(), (old, old))
    assert vh._acquire() is True                                      # fil perdu (serveur redémarré) : repris
    vh._lock_path().unlink()


def test_etat_du_montage_pendant_la_generation_et_apres_le_lancement(monkeypatch, world):
    monkeypatch.setattr(hf, "status", lambda db: {"connected": True, "video_left_today": 5, "left_today": 5})
    vh.start(FakeDB(), SPEC, "u1")
    out = vs.status(FakeDB())
    assert out["state"] == "building" and out["ai"] == {"done": 0, "total": 2}
    job = json.loads(world["store"][vh.KEY]); job.update(state="rendering", dispatched_at=time.time()); world["store"][vh.KEY] = json.dumps(job)
    monkeypatch.setattr(repair, "_ctx", lambda db: ("tok", "o/r", "main"))
    old = {"workflow_runs": [{"id": 1, "status": "completed", "conclusion": "success", "created_at": "2020-01-01T00:00:00Z"}]}
    monkeypatch.setattr(repair, "_gh", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: old))
    assert vs.status(FakeDB())["state"] == "building"               # l'ancien montage ne doit pas passer pour le nouveau


def test_le_moteur_accepte_les_medias_ia_et_refuse_les_adresses_douteuses():
    import importlib.util, pathlib
    m = importlib.util.spec_from_file_location("video_spec_ai", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py")
    eng = importlib.util.module_from_spec(m); m.loader.exec_module(eng)
    ok = eng.clean(vh.to_engine({"format": "vertical", "theme": "earth", "scenes": SPEC["scenes"]},
                                {"1": {"url": "https://cdn.example/lion.mp4"}, "3": {"url": "https://cdn.example/cub.png"}}))
    assert [s["type"] for s in ok["scenes"]] == ["title", "clip", "text", "photo"] and ok["scenes"][1]["seconds"] == 8 and ok["scenes"][3]["src"] == "https://cdn.example/cub.png"
    for bad in ("http://cdn.example/a.mp4", "https://10.0.0.1/a.mp4", "https://user:pw@cdn.example/a.mp4", "https://localhost/a.mp4", "https://x.local/a.mp4", "file:///etc/passwd", ""):
        with pytest.raises(ValueError):
            eng.clean({"format": "vertical", "scenes": [{"type": "clip", "url": bad, "seconds": 5}]})
    with pytest.raises(ValueError):
        eng.clean({"format": "vertical", "scenes": [{"type": "photo", "url": "http://cdn.example/a.png"}]})


def test_lancement_envoie_les_scenes_ia_a_higgsfield_seulement_si_activees(monkeypatch):
    from app import video_media
    sent = {}
    monkeypatch.setattr(vs, "images", lambda db=None: [])
    monkeypatch.setattr(video_media, "items_by_id", lambda db: {})
    monkeypatch.setattr(vh, "start", lambda db, spec, uid: sent.update(hybrid=spec) or {"state": "assets"})
    monkeypatch.setattr(vh, "clear", lambda db: None)
    monkeypatch.setattr(vs, "dispatch", lambda db, spec: sent.update(montage=spec) or {"state": "queued"})
    scenes = [{"type": "ai_clip", "seconds": 6, "prompt": "Un lion court dans la savane au coucher du soleil"}, {"type": "title", "l1": "LION"}]
    monkeypatch.setattr(vs, "ai_enabled", lambda db: True)
    assert vs.start(FakeDB(), {"format": "vertical", "scenes": scenes})["state"] == "assets"
    assert [s["type"] for s in sent["hybrid"]["scenes"]] == ["ai_clip", "title"] and "montage" not in sent   # IA générée d'abord, montage ensuite
    sent.clear()
    monkeypatch.setattr(vs, "ai_enabled", lambda db: False)                             # coupées par le patron : scène IA écartée
    assert vs.start(FakeDB(), {"format": "vertical", "scenes": scenes})["state"] == "queued"
    assert [s["type"] for s in sent["montage"]["scenes"]] == ["title"] and "hybrid" not in sent
