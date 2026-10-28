"""Mesures dites à la française : « 4m50 sur 2m60 » se lisait 50 × 2 m (cloison de 50 m !), « 3 mètres 20 » devenait 20 m,
« mètres carrés » et « cinq mètres sur quatre » n'étaient pas compris. Le calcul direct du chat donnait alors des quantités
fausses. Chaque écriture courante est maintenant ramenée à la bonne mesure avant tout calcul."""
import pytest

from app import calc, orchestrator


@pytest.mark.parametrize("text, expected", [
    ("cloison de 4m50 sur 2m60", {"length_m": 4.5, "height_m": 2.6}),
    ("faux plafond 5m20 x 3m80", {"length_m": 5.2, "width_m": 3.8}),
    ("cloison 3 mètres 20 sur 2 mètres 50", {"length_m": 3.2, "height_m": 2.5}),
    ("plafond de cinq mètres sur quatre", {"length_m": 5.0, "width_m": 4.0}),
    ("cloison deux faces de 4 m sur 2 mètres et demi", {"length_m": 4.0, "height_m": 2.5, "sides": 2}),
    ("cloison de deux virgule cinq sur trois", {"length_m": 2.5, "height_m": 3.0}),
    ("cloison 12m50 x 2m70 une face", {"length_m": 12.5, "height_m": 2.7, "sides": 1}),
    ("cloison 6 mètres 2 portes hauteur 2,5", {"length_m": 6.0, "height_m": 2.5}),      # « 6 mètres 2 portes » : pas 6,2 m
    ("un plafond de 5 sur 4", {"length_m": 5.0, "width_m": 4.0}),                        # « un plafond » : pas une mesure
])
def test_mesures_ecrites_a_la_francaise(text, expected):
    r = calc.calculate_from_text(text)
    assert {k: r.inputs[k] for k in expected} == expected


@pytest.mark.parametrize("raw, normal", [
    ("plafond de 20 mètres carrés", "plafond de 20 m²"),
    ("faux plafond de 35 metres carres", "faux plafond de 35 m²"),
    ("plafond 20 m2", "plafond 20 m2"),                                                    # m2 = m², jamais 20,2 m
    ("cloison 2m05 sur 3", "cloison 2.05 m sur 3"),
])
def test_ecritures_ramenees_a_une_forme_simple(raw, normal):
    assert calc.normalize_dimensions(raw) == normal


def test_le_chat_route_ces_mesures_vers_le_bon_calcul():
    assert orchestrator._intent("cloison 3 mètres 20 sur 2 mètres 50", {}) == "calculate"
    assert orchestrator._intent("faux plafond de cinq mètres sur quatre", {}) == "calculate"
    assert calc.detect_calc_kind("j'ai une surface de 100 mètres carrés") == "a_preciser"   # jamais supposé cloison
    assert orchestrator._intent("c'est quoi un faux plafond ?", {}) == "chat"


@pytest.mark.parametrize("text, sides", [
    ("cloison 6 m sur 2,5 m simple face", 1),
    ("cloison 6 m sur 2,5 m une seule face", 1),
    ("cloison 6 m sur 2,5 m sur un côté", 1),
    ("doublage 6 m sur 2,5 m", 1),                      # un doublage habille un mur : une face
    ("doublage 6 m sur 2,5 m des deux côtés", 2),
    ("cloison 6 m sur 2,5 m double face", 2),
    ("cloison 6 m sur 2,5 m", 2),
])
def test_faces_dites_autrement_ne_doublent_plus_les_plaques(text, sides):
    assert calc.calculate_from_text(text).inputs["sides"] == sides


@pytest.mark.parametrize("text, openings", [
    ("cloison 8 m sur 2,6 m avec deux portes de 0,90 sur 2,10", [("door", 0.9, 2.1, 2, False)]),
    ("cloison 4m50 sur 2m60 avec une porte 0m90 x 2m10", [("door", 0.9, 2.1, 1, False)]),
    ("cloison 8 m sur 2,6 m avec une porte de 90 sur 210", [("door", 0.9, 2.1, 1, False)]),     # centimètres
    ("cloison 8 m sur 2,6 m avec 3 fenêtres de 120 par 100", [("window", 1.2, 1.0, 3, False)]),
    ("cloison 8 m sur 2,6 m avec 1 porte et 2 fenêtres", [("door", 0.9, 2.04, 1, True), ("window", 1.2, 1.2, 2, True)]),
])
def test_portes_et_fenetres_gardent_taille_et_nombre(text, openings):
    got = calc.calculate_from_text(text).inputs["openings"]
    assert [(o["kind"], o["width"], o["height"], o["quantity"], o["assumed_size"]) for o in got] == openings
