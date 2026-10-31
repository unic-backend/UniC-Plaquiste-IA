"""Montage réel des vidéos du patron (scripts/video/spec.py + edit.py) : vitesse, couleurs, cadrage, zoom, arrêt sur image, écran partagé, transitions."""
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video"
FFMPEG = shutil.which("ffmpeg") is not None


def _load(name):
    sys.path.insert(0, str(ROOT))
    try:
        m = importlib.util.spec_from_file_location(f"video_{name}_montage", ROOT / f"{name}.py")
        mod = importlib.util.module_from_spec(m)
        m.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(ROOT))


sp, ed = _load("spec"), _load("edit")
URL = "https://cdn.example.com/a.mp4"


def _clip(**kw):
    return sp.clean({"scenes": [{"type": "clip", "url": URL, "seconds": 4, **kw}]})["scenes"][0]


def test_montage_valide_et_borne():
    c = _clip(speed=0.5, grade="cinema", focus={"x": 0.5, "y": 0.2}, zoom="punch", zoom_amount=9, freeze=1.5, transition="flash",
              split={"url": "https://cdn.example.com/b.mp4", "start": 3})
    assert (c["speed"], c["grade"], c["focus"], c["zoom"], c["zoom_amount"], c["freeze"], c["transition"]) == (0.5, "cinema", {"x": 0.5, "y": 0.2}, "punch", 1.6, 1.5, "flash")
    assert c["split"] == {"url": "https://cdn.example.com/b.mp4", "start": 3.0}
    plain = _clip(speed=1, grade="sepia", focus={"x": 0.5, "y": 0.5}, zoom="tourbillon", freeze=0, transition="fade")
    assert not {"speed", "grade", "focus", "zoom", "freeze", "transition", "split"} & set(plain)          # sans effet ou inconnu : rien
    assert _clip(speed=99)["speed"] == 4 and _clip(speed=0.01)["speed"] == 0.25 and _clip(freeze=9)["freeze"] == 3 and "freeze" not in _clip(freeze=3, seconds=3)   # au moins 1 s de film
    with pytest.raises(ValueError):
        _clip(split={"url": "http://localhost/b.mp4"})                                                   # second film : même contrôle d'adresse
    assert set(sp.GRADES) == set(ed.GRADE_VF)                                                           # chaque étalonnage a son filtre


def test_commande_ffmpeg_du_plan_monte():
    c = _clip(start=2, speed=0.5, grade="night", focus={"x": 0.5, "y": 0.2}, freeze=1)
    a = ed.ffmpeg_args(c, "src.mp4", None, 1080, 1920, 30, 120, "out/%05d.jpg")
    vf = a[a.index("-vf") + 1]
    assert a[a.index("-t") + 1] == "1.500" and a[a.index("-ss") + 1] == "2"                 # 3 s de film au ralenti ×0,5 = 1,5 s de source, puis 1 s figée
    assert vf.startswith("setpts=(PTS-STARTPTS)/0.5,fps=30,") and "crop=1080:1920:(iw-1080)*0.5:(ih-1920)*0.2" in vf
    assert ed.GRADE_VF["night"] in vf and vf.endswith("tpad=stop_mode=clone:stop_duration=4") and a[-1] == "out/%05d.jpg"
    s = _clip(split={"url": "https://cdn.example.com/b.mp4", "start": 5})
    b = ed.ffmpeg_args(s, "a.mp4", "b.mp4", 1080, 1920, 30, 120, "o/%05d.jpg")
    fc = b[b.index("-filter_complex") + 1]
    assert b.count("-i") == 2 and "hstack=inputs=2" in fc and "crop=540:1920" in fc and "drawbox=x=536" in fc and b[b.index("-map") + 1] == "[v]"
    assert ed.ffmpeg_args(s, "a.mp4", None, 1080, 1920, 30, 120, "o/%05d.jpg").count("-i") == 1         # second film absent : plan simple


def test_zoom_et_transitions_image_par_image():
    z = {"zoom": "in", "zoom_amount": 1.2, "focus": {"x": 0.5, "y": 0.2}}
    assert ed.zoom_box(z, 0, 90, 30, 1080, 1920) is None and ed.zoom_factor(z, 89, 90, 30) == pytest.approx(1.2)
    x0, y0, x1, y1 = ed.zoom_box(z, 89, 90, 30, 1080, 1920)
    assert (x1 - x0, y1 - y0) == pytest.approx((900, 1600)) and y0 == pytest.approx(64)                 # resserré vers le haut (cadrage)
    assert ed.zoom_factor({"zoom": "out", "zoom_amount": 1.3}, 0, 90, 30) == pytest.approx(1.3)
    p = {"zoom": "punch", "zoom_amount": 1.25}
    assert ed.zoom_factor(p, 30, 90, 30) == 1.0 and ed.zoom_factor(p, 37, 90, 30) == pytest.approx(1.25)    # coup de zoom à 35 % du plan, en 0,18 s
    clip = {"kind": "clip"}
    m = ed.mix({}, {"kind": "html"}, 0, 90, 30, True)
    assert m == {"dark": 0.0, "white": 1.0, "slide": None} and ed.mix({}, None, 89, 90, 30, True)["dark"] == 0.0   # fondu par défaut, comme avant
    assert ed.mix({}, {**clip, "transition": "cut"}, 89, 90, 30, True)["dark"] == 1.0                       # le plan suivant coupe : pas de fondu de sortie
    assert ed.mix({"transition": "cut"}, None, 0, 90, 30, True)["dark"] == 1.0
    assert ed.mix({"transition": "flash"}, None, 0, 90, 30, True)["white"] == 0.0 and ed.mix({"transition": "flash"}, None, 8, 90, 30, True)["white"] == 1.0
    assert ed.mix({"transition": "slide"}, None, 0, 90, 30, True)["slide"] == 0.0 and ed.mix({"transition": "slide"}, None, 12, 90, 30, True)["slide"] is None
    assert ed.mix({"transition": "slide"}, None, 0, 90, 30, False) == {"dark": 0.0, "white": 1.0, "slide": None}   # rien à pousser : fondu


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg absent")
def test_rendu_reel_ralenti_partage_et_arret_sur_image(tmp_path):
    for n in ("a", "b"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=d=6:s=320x240:r=25", "-pix_fmt", "yuv420p",
                        str(tmp_path / f"{n}.mp4")], check=True)
    c = _clip(seconds=3, speed=0.5, freeze=1, grade="cinema", split={"url": "https://cdn.example.com/b.mp4", "start": 2})
    out = tmp_path / "f"
    out.mkdir()
    subprocess.run(ed.ffmpeg_args(c, tmp_path / "a.mp4", tmp_path / "b.mp4", 360, 640, 24, 72, str(out / "%05d.jpg")), check=True)
    files = sorted(out.glob("*.jpg"))
    assert len(files) == 72
    from PIL import Image, ImageChops
    assert Image.open(files[0]).size == (360, 640)
    assert ImageChops.difference(Image.open(files[-1]).convert("RGB"), Image.open(files[-20]).convert("RGB")).getbbox() is None   # dernière seconde figée
    assert ImageChops.difference(Image.open(files[0]).convert("RGB"), Image.open(files[30]).convert("RGB")).getbbox() is not None  # avant : ça bouge
    px = Image.open(files[10]).convert("RGB").getpixel((179, 320))
    assert px[0] > 180 and px[1] > 140 and px[2] < 120                                                   # trait doré au milieu de l'écran partagé


def test_cartons_de_sous_titres():
    w = [[0.0, 0.3, "Il"], [0.3, 0.6, "vient"], [0.6, 0.9, "de"], [0.9, 1.4, "sortir."], [1.5, 1.8, "Opus"], [1.8, 2.1, "5.5"],
         [3.5, 3.9, "Incroyablement"], [3.9, 4.4, "puissant"], [9.0, 9.5, "hors"], ["x", 1, "bad"], [1, 2]]
    g = sp.caption_groups(w, 5.0)
    assert [x[2] for x in g] == ["Il vient de", "sortir.", "Opus 5.5", "Incroyablement", "puissant"]   # 3 mots, ponctuation, pause, 16 caractères
    assert g[0][:2] == [0.0, 0.9] and g[1][1] == 1.5 and g[2][1] == 2.35                                # enchaîné ; sinon +0,25 s après le dernier mot
    assert sp.caption_groups("pas une liste", 5) == [] and sp.caption_groups(w, 0) == []
    c = sp.clean({"scenes": [{"type": "clip", "url": URL, "seconds": 4, "captions": [[0.1, 0.5, "<b>Salut</b>"]]},
                             {"type": "kinetic", "lines": ["A"], "captions": [[0.2, 0.6, "Voix"]]}]})["scenes"]
    assert c[0]["caps"] == [[0.1, 0.75, "bSalut/b"]] and c[1]["caps"][0][2] == "Voix"                  # jamais de balise ; voix off sur une scène texte aussi
    assert "caps" not in sp.clean({"scenes": [{"type": "clip", "url": URL, "captions": []}]})["scenes"][0]


def test_panneaux_et_ecran_divise():
    c = sp.clean({"scenes": [{"type": "clip", "url": URL, "seconds": 6, "layout": "split", "split": {"url": "https://cdn.example.com/b.mp4"},
                              "panels": [[3, 0, {"type": "counter", "value": 0, "suffix": "€", "label": "gratuit"}], [0, 1.5, {"type": "badge", "lines": ["Opus"]}],
                                         [1, 0, {"type": "flow", "steps": ["seule"]}], [9, 0, {"type": "chat", "lines": ["21"]}], [2, 0, {"type": "inconnu"}]]}]})["scenes"][0]
    assert c["layout"] == "split" and "split" not in c                                                 # jamais écran divisé ET avant | après
    assert [(p[0], p[1], p[2]["type"]) for p in c["panels"]] == [(0, 1.5, "badge"), (3, 0, "counter")]   # triés ; invalides et hors du plan écartés
    assert c["panels"][1][2]["label"] == "GRATUIT"
    for t, extra in (("counter", {"value": 12.5, "suffix": "%"}), ("flow", {"steps": ["A", "B", "C"]}), ("wave", {}), ("chat", {"lines": ["21", "Guide"]}), ("badge", {"lines": ["Opus"]})):
        assert sp.clean({"scenes": [{"type": t, **extra}]})["scenes"][0]["type"] == t                  # aussi en scène entière
    with pytest.raises(ValueError):
        sp.clean({"scenes": [{"type": "counter", "value": "beaucoup"}]})
    a = ed.ffmpeg_args({**c, "seconds": 6}, "a.mp4", None, 1080, 1920, 30, 180, "o/%05d.jpg")
    vf = a[a.index("-vf") + 1]
    assert ed.bottom_height(1920) == 1056 and "crop=1080:1056" in vf and "pad=1080:1920:0:864" in vf     # la personne en bas (55 %)
    box = ed.zoom_box({"zoom": "in", "zoom_amount": 1.2}, 89, 90, 30, 1080, 1056, 864)
    assert box[1] >= 864 and box[3] <= 1920                                                             # zoom seulement dans la partie filmée


def test_animations_lottie_sures():
    import json
    assert set(sp.BUILTIN_LOTTIE) == {"check", "spark", "arrow", "pin", "pulse"}
    for n in sp.BUILTIN_LOTTIE:                                                                            # animations du moteur : valides et sûres
        d = json.loads((ROOT / "lottie" / f"{n}.json").read_text())
        assert sp.sanitize_lottie(d)["layers"] and d["fr"] == 30
    good = {"v": "5.7", "fr": 30, "ip": 0, "op": 60, "w": 200, "h": 200, "layers": [{"ty": 4}],
            "fonts": {"list": [{"fPath": "https://evil.example/f.css"}]},
            "assets": [{"id": "a", "p": "https://evil.example/x.png", "u": ""}, {"id": "b", "p": "data:image/png;base64,AAAA"}, {"id": "c", "layers": []},
                       {"id": "d", "u": "images/", "p": "data:image/png;base64,AAAA"}]}
    c = sp.sanitize_lottie(good)
    assert [a["id"] for a in c["assets"]] == ["b", "c"] and "fonts" not in c                               # rien de l'extérieur
    for bad in ({}, {**good, "layers": []}, {**good, "fr": 0}, {**good, "op": 99999}, "x"):
        with pytest.raises(ValueError):
            sp.sanitize_lottie(bad)
    s = sp.clean({"scenes": [{"type": "lottie", "anim": "check", "lines": ["Validé"]}, {"type": "lottie", "url": "https://cdn.example.com/a.json", "loop": True}]})["scenes"]
    assert s[0]["anim"] == "check" and s[1]["url"].endswith("a.json") and s[1]["loop"] is True and "bg" not in s[1]   # le lien n'est pas un fond
    for bad in ({"type": "lottie"}, {"type": "lottie", "anim": "inconnue"}, {"type": "lottie", "url": "http://localhost/a.json"}):
        with pytest.raises(ValueError):
            sp.clean({"scenes": [bad]})
    assert "lottie/lottie_light.min.js" in (ROOT / "scenes.html").read_text() and "eval(" not in (ROOT / "lottie" / "lottie_light.min.js").read_text()
