"""Effets « cinéma » du moteur vidéo (scripts/video/spec.py) : machine à écrire, titre animé, liste cochée, néon, slogan, texte incrusté sur un clip."""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video"


def _eng():
    m = importlib.util.spec_from_file_location("video_spec_fx", ROOT / "spec.py")
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    return eng


def test_scenes_effets_valides_et_bornees():
    eng = _eng()
    out = eng.clean({"scenes": [
        {"type": "typewriter", "lines": ["JOJ Dakar 2026", "<script>x", "3", "4"], "image": "ref-dakar-arena.webp", "reveal": "dots"},
        {"type": "kinetic", "tag": "Site 01", "place": "Diamniadio", "lines": ["Stade", "Abdoulaye Wade"], "seconds": 99},
        {"type": "checklist", "heading": "Nos interventions", "items": ["Bureaux", "Zones antidopage", "Mégastore"]},
        {"type": "neon", "lines": ["Dakar", "Arena", "trop"]},
        {"type": "slogan", "l1": "L'Afrique accueille.", "l2": "Dakar célèbre.", "brand": "UniC Plaquiste", "lines": ["+221 77 708 50 92"]},
    ]})
    tw, ki, ck, ne, sl = out["scenes"]
    assert tw["lines"] == ["JOJ Dakar 2026", "scriptx", "3"] and tw["reveal"] == "dots"          # 3 lignes au plus, aucun chevron
    assert tw["bg"] == "https://www.unicplaquiste.com/images/ref-dakar-arena.webp"
    assert ki["lines"] == ["STADE", "ABDOULAYE WADE"] and ki["tag"] == "SITE 01" and ki["place"] == "DIAMNIADIO" and ki["seconds"] == 10
    assert ck["items"] == ["Bureaux", "Zones antidopage", "Mégastore"] and ck["seconds"] == 4.0 and "bg" not in ck
    assert ne["lines"] == ["DAKAR", "ARENA"]
    assert sl["l2"] == "DAKAR CÉLÈBRE." and sl["lines"] == ["+221 77 708 50 92"]


@pytest.mark.parametrize("bad", [
    {"type": "typewriter", "lines": []},
    {"type": "kinetic", "lines": [""]},
    {"type": "checklist", "items": []},
    {"type": "neon"},
    {"type": "slogan", "brand": "x"},
    {"type": "kinetic", "lines": ["A"], "image": "../../etc/passwd"},
    {"type": "kinetic", "lines": ["A"], "url": "http://169.254.169.254/x.jpg"},
])
def test_scenes_effets_refusees(bad):
    with pytest.raises(ValueError):
        _eng().clean({"scenes": [bad]})


def test_texte_incruste_sur_un_clip():
    eng = _eng()
    clip = eng.clean({"scenes": [{"type": "clip", "url": "https://cdn.example.com/a.mp4", "seconds": 6,
                                  "overlay": {"type": "kinetic", "lines": ["Des mains", "expertes."], "seconds": 2, "image": "ref-dakar-arena.webp"}}]})["scenes"][0]
    ov = clip["overlay"]
    assert ov["type"] == "kinetic" and ov["lines"] == ["DES MAINS", "EXPERTES."]
    assert ov["seconds"] == clip["seconds"] == 6.0 and "bg" not in ov          # même durée que le film, jamais de fond
    for t in ("slogan", "title", "page"):                                       # seuls les 4 effets texte s'incrustent
        c = eng.clean({"scenes": [{"type": "clip", "url": "https://cdn.example.com/a.mp4", "overlay": {"type": t, "l1": "x", "lines": ["x"]}}]})["scenes"][0]
        assert "overlay" not in c


def test_moteur_html_sans_interpretation_du_scenario():
    """Le texte du scénario passe par textContent : seule la coche (constante du moteur) utilise innerHTML."""
    html = (ROOT / "scenes.html").read_text(encoding="utf-8")
    assert html.count("innerHTML") == 1 and "sv.innerHTML = CHECK" in html
    for t in ("typewriter", "kinetic", "checklist", "neon", "slogan"):
        assert f'"{t}"' in html
