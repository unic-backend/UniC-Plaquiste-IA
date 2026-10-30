"""Le Studio (IA) sait écrire les effets cinéma du moteur : machine à écrire, titre animé, liste cochée, néon, slogan, texte sur un clip IA."""
import importlib.util
import pathlib

from app import video_hybrid
from app import video_studio as vs

NAMES = ["ref-stade-01.webp", "ref-dakar-arena.webp"]


def _engine():
    p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "spec.py"
    m = importlib.util.spec_from_file_location("video_spec_studio_fx", p)
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    return eng


SCENES = [
    {"type": "typewriter", "lines": ["JOJ Dakar 2026", "x" * 200], "image": "ref-stade-01.webp", "reveal": True},
    {"type": "kinetic", "tag": "Site 01", "place": "Diamniadio", "lines": ["Stade", "Abdoulaye Wade"], "image": "inconnue.webp"},
    {"type": "checklist", "heading": "Nos interventions", "checks": ["Bureaux", "Zones antidopage", "Mégastore"]},
    {"type": "neon", "lines": ["Dakar", "Arena", "trop"]},
    {"type": "slogan", "l1": "L'Afrique accueille.", "l2": "Dakar célèbre.", "brand": True, "lines": ["+33 1 23 45 67 89"]},
    {"type": "checklist", "checks": []},                       # vide : écartée
]


def test_effets_construits_depuis_le_catalogue():
    sp = vs.build_spec("vertical", SCENES, NAMES)
    tw, ki, ck, ne, sl = sp["scenes"]
    assert tw["image"] == "ref-stade-01.webp" and tw["reveal"] == "dots" and len(tw["lines"][1]) <= 60
    assert "image" not in ki                                    # photo hors catalogue : pas de fond
    assert ck["items"] == ["Bureaux", "Zones antidopage", "Mégastore"]
    assert ne["lines"] == ["Dakar", "Arena"]
    assert sl["brand"] == "UNIC PLAQUISTE" and sl["lines"] == [vs.FACTS["phone"], vs.FACTS["site"]]   # carte : faits du code, jamais de l'IA
    assert tw["seconds"] >= vs._readable(tw) or tw["seconds"] == vs.SECONDS["typewriter"][1]           # le temps de tout taper


def test_aller_retour_et_contrat_moteur():
    sp = vs.build_spec("vertical", SCENES, NAMES)
    again = vs.build_spec("vertical", sp["scenes"], NAMES)                                            # scénario renvoyé par l'appli
    assert again["scenes"] == sp["scenes"]
    out = _engine().clean(sp)
    assert [s["type"] for s in out["scenes"]] == ["typewriter", "kinetic", "checklist", "neon", "slogan"]
    assert out["scenes"][0]["bg"].endswith("/ref-stade-01.webp") and out["scenes"][4]["l2"] == "DAKAR CÉLÈBRE."


def test_texte_incruste_sur_un_clip_ia():
    sp = vs.build_spec("vertical", [{"type": "ai_clip", "prompt": "un tambourineur dans un stade au crépuscule", "seconds": 5,
                                     "overlay": {"type": "kinetic", "lines": ["Une équipe."], "image": "ref-stade-01.webp"}},
                                    {"type": "ai_clip", "prompt": "un plafond lumineux en BA13", "overlay": {"type": "slogan", "l1": "x"}}],
                       NAMES, ai={"clips": 2})
    a, b = sp["scenes"]
    assert a["overlay"]["lines"] == ["Une équipe."] and "image" not in a["overlay"] and "seconds" not in a["overlay"]
    assert "overlay" not in b                                                                           # slogan : jamais incrusté
    eng = video_hybrid.to_engine(sp, {"0": {"url": "https://cdn.example.com/a.mp4"}, "1": {"url": "https://cdn.example.com/b.mp4"}})
    clip = _engine().clean(eng)["scenes"][0]
    assert clip["type"] == "clip" and clip["overlay"]["lines"] == ["UNE ÉQUIPE."] and clip["overlay"]["seconds"] == clip["seconds"]


def test_outil_et_consignes_connaissent_les_effets():
    enum = vs.TOOL["input_schema"]["properties"]["scenes"]["items"]["properties"]["type"]["enum"]
    assert set(vs.FX_TYPES) <= set(enum) and "overlay" in vs.SCENE_PROPS and "checks" in vs.SCENE_PROPS
    assert "typewriter" in vs.SYSTEM and "points-pixels" in vs.SYSTEM
