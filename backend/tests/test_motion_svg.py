"""Animations libres dessinées par l'IA (scène « motion ») : le Studio n'est plus limité à une liste d'effets. Le SVG animé en CSS qu'écrit
l'IA est nettoyé (dessin seulement, rien d'externe, aucun script), accepté par le moteur, et le scénariste sait qu'une scène montre toujours
le contenu (jamais un effet décoratif seul)."""
import importlib.util
import pathlib

from app import motion_svg as ms
from app import video_studio as vs

DRAW = ('<svg viewBox="0 0 1080 1920"><style>@keyframes up{from{opacity:0;transform:translateY(80px)}to{opacity:1}} .t{animation:up 1s .3s both;'
        'fill:url(#g)}</style><defs><linearGradient id="g"><stop offset="0" stop-color="#38bdf8"/></linearGradient></defs>'
        '<rect width="1080" height="1920" fill="#05070d"/><text class="t" x="540" y="960" text-anchor="middle">IMAGINE</text><use href="#g"/></svg>')


def _engine():
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    m = importlib.util.spec_from_file_location("video_spec_motion", path)
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    return eng


def test_le_dessin_et_ses_animations_css_sont_gardes():
    out = ms.clean(DRAW, "vertical")
    for keep in ("@keyframes up", "animation:up 1s .3s both", "url(#g)", "<linearGradient", "IMAGINE", 'href="#g"'):
        assert keep in out
    assert 'width="100%"' in out and 'preserveAspectRatio="xMidYMid slice"' in out


def test_tout_ce_qui_sort_du_dessin_est_retire():
    bad = ('<svg><script>fetch("https://x")</script><rect onload="x()" onclick="y()" width="9"/><image href="https://e.com/a.png"/>'
           '<foreignObject><div>html</div></foreignObject><use href="https://evil/#x"/><a href="https://x"><rect/></a>'
           '<style>@import url(https://x/s.css);</style><rect fill="url(https://x/p.svg#a)"/><rect style="background:url(data:x)"/>'
           '<rect fill="javascript:alert(1)"/><iframe src="https://x"/></svg>')
    out = ms.clean(bad, "square")
    for gone in ("script", "onload", "onclick", "<image", "foreignObject", "https://", "@import", "javascript:", "data:", "iframe", "<a"):
        assert gone not in out
    assert out.count("<rect") == 4 and 'viewBox="0 0 1080 1080"' in out           # le dessin reste, cadré au format carré


def test_svg_refuse_quand_il_est_illisible_ou_trop_gros():
    for bad in (None, "", "<div/>", "<svg><rect>", '<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "<svg>" + "<g/>" * 2000 + "</svg>",
                "<svg>" + "x" * (ms.MAX_CHARS + 1) + "</svg>"):
        assert ms.clean(bad) is None
    assert 'viewBox="0 0 1920 1080"' in ms.clean("<svg><rect/></svg>", "horizontal")


def test_la_scene_motion_passe_du_serveur_au_moteur():
    spec = vs.build_spec("vertical", [{"type": "motion", "seconds": 7, "svg": DRAW}, {"type": "motion", "svg": "<script/>"},
                                      {"type": "title", "l1": "FIN"}], [])
    assert [s["type"] for s in spec["scenes"]] == ["motion", "title"] and spec["scenes"][0]["seconds"] == 7    # SVG illisible : scène écartée
    eng = _engine()
    out = eng.clean(spec)
    assert out["scenes"][0]["type"] == "motion" and "@keyframes" in out["scenes"][0]["svg"]
    for raw in ('<svg><image href="https://x/a.png"/></svg>', '<svg onload="x()"/>', "<div/>", '<svg><rect fill="url(http://x)"/></svg>'):
        try:
            eng.clean({"scenes": [{"type": "motion", "svg": raw}]})
        except ValueError:
            continue
        raise AssertionError(f"le moteur aurait accepté : {raw}")


def test_le_scenariste_peut_dessiner_et_ne_fait_plus_de_stickers():
    types = vs.SCENE_PROPS["type"]["enum"]
    assert "motion" in types and "svg" in vs.SCENE_PROPS
    assert "DESSINE-LE toi-même" in vs.SYSTEM and "jamais une animation décorative seule" in vs.SYSTEM
    assert "jamais le nom d'un effet affiché à l'écran" in vs.SYSTEM
