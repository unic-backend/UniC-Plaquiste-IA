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
