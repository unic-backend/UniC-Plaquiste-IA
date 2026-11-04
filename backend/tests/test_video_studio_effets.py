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


def test_grille_de_points_etapes_au_trait_et_trajet():
    sp = vs.build_spec("vertical", [
        {"type": "dots", "value": 180, "suffix": "+", "label": "chantiers livrés", "highlight": 40},
        {"type": "dots", "value": 1200},                                     # trop de points pour les compter : écartée
        {"type": "dots", "value": 12.5},                                     # un point par unité : jamais une fraction
        {"type": "bars", "steps": ["Tracé", "Ossature", "Plaques", "Joints", "Peinture", "Déco", "Septième"], "label": "chaque étape compte"},
        {"type": "bars", "steps": ["seule"]},                                # une barre n'est pas une progression : écartée
        {"type": "route", "lines": ["Dakar", "Diamniadio"], "value": 28, "suffix": "km"},
        {"type": "route", "lines": ["Paris", "Tokyo"]},                      # sans distance sûre : le trajet seul
        {"type": "route", "lines": ["Dakar"]}], NAMES)
    dots, bars, r1, r2 = sp["scenes"]
    assert dots["value"] == 180 and dots["highlight"] == 12 and dots["suffix"] == "+"                 # au plus 12 points en or
    assert len(bars["steps"]) == 6 and bars["label"] == "chaque étape compte"
    assert r1["value"] == 28 and r1["suffix"] == "km" and "value" not in r2
    assert all(s["seconds"] >= vs.SECONDS[s["type"]][0] for s in sp["scenes"])
    out = _engine().clean(sp)                                                                          # le moteur accepte ce que le Studio écrit
    assert [s["type"] for s in out["scenes"]] == ["dots", "bars", "route", "route"]
    assert out["scenes"][0]["label"] == "CHANTIERS LIVRÉS" and out["scenes"][0]["highlight"] == 12 and "value" not in out["scenes"][3]


def test_scenes_3d_vue_eclatee_et_salon():
    sp = vs.build_spec("vertical", [
        {"type": "layers3d", "heading": "Une cloison, couche par couche", "layers": ["Bandes + enduit", "Plaque BA13", "Laine 45 mm", "Montants", "Rails", "Sol", "Septième"]},
        {"type": "layers3d", "layers": ["seule"]},                                          # une couche ne s'éclate pas : écartée
        {"type": "room3d", "lines": ["Et si…", "…ton plafond s'allumait ?", "trop"], "seconds": 99}], NAMES)
    lay, room = sp["scenes"]
    assert len(lay["layers"]) == 6 and lay["heading"] == "Une cloison, couche par couche"
    assert room["lines"] == ["Et si…", "…ton plafond s'allumait ?"] and room["seconds"] == vs.SECONDS["room3d"][1]
    out = _engine().clean(sp)["scenes"]                                                    # le moteur accepte ce que le Studio écrit
    assert [s["type"] for s in out] == ["layers3d", "room3d"] and out[0]["layers"][0] == "Bandes + enduit"


def test_courbe_et_code_pour_tous_les_domaines():
    sp = vs.build_spec("vertical", [
        {"type": "chart", "values": [100, 104, "x", 98, 121], "suffix": "$", "label": "cours (exemple)"},   # une valeur non chiffrée est écartée
        {"type": "chart", "values": [7]},                                                                  # un seul point n'est pas une courbe
        {"type": "code", "label": "moyenne.py", "code": ["def moyenne(notes):", "\treturn sum(notes) / len(notes)", "", "if a < b:", "", ""]},
        {"type": "code", "code": ["", "  "]}], NAMES)
    ch, co = sp["scenes"]
    assert ch["values"] == [100, 104, 98, 121] and ch["suffix"] == "$" and ch["label"] == "cours (exemple)"
    assert co["lines"] == ["def moyenne(notes):", "    return sum(notes) / len(notes)", "", "if a < b:"]   # indentation et « < » gardés, vides du bout retirés
    assert co["seconds"] >= vs._readable(co) or co["seconds"] == vs.SECONDS["code"][1]                       # le temps de tout taper
    out = _engine().clean(sp)["scenes"]
    assert [s["type"] for s in out] == ["chart", "code"] and out[1]["lines"][1].startswith("    return") and out[0]["label"] == "COURS (EXEMPLE)"
