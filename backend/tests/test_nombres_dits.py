"""Mesures DITES à voix haute (le patron dicte) : « deux mètres soixante » se lisait 2 m (le « soixante » perdu, la hauteur fausse),
« dix-huit » devenait « dix-8 », « soixante-dix » n'était pas compris. Les nombres composés français sont maintenant lus en entier."""
import pytest

from app import calc


@pytest.mark.parametrize("words, value", [
    ("dix-huit", 18), ("soixante-dix", 70), ("soixante et onze", 71), ("quatre-vingts", 80), ("quatre-vingt-dix", 90),
    ("quatre-vingt-quinze", 95), ("vingt et un", 21), ("trente-cinq", 35), ("soixante-dix-huit", 78), ("cent", 100),
    ("cent vingt", 120), ("deux cent cinquante", 250), ("trois cents", 300),
])
def test_nombres_composes(words, value):
    assert calc.spoken_number(words) == value


@pytest.mark.parametrize("text, expected", [
    ("cloison de trois mètres cinquante sur deux mètres soixante", {"length_m": 3.5, "height_m": 2.6}),   # avant : 2 m de haut
    ("cloison trois mètres et demi sur deux mètres cinquante", {"length_m": 3.5, "height_m": 2.5}),
    ("cloison deux faces de cinq mètres sur deux mètres soixante-dix", {"length_m": 5.0, "height_m": 2.7}),
    ("cloison sept mètres sur deux mètres quarante", {"length_m": 7.0, "height_m": 2.4}),
    ("cloison six mètres deux portes hauteur deux mètres cinquante", {"length_m": 6.0, "height_m": 2.5}),   # « 2 portes » reste 2 portes
    ("faux plafond quatre mètres sur trois mètres cinquante", {"length_m": 4.0, "width_m": 3.5}),
    ("un faux plafond de cinq sur quatre", {"length_m": 5.0, "width_m": 4.0}),                          # « un » n'est pas une mesure
    ("moulure dix-huit mètres", {"length_ml": 18.0}),
    ("corniche vingt-cinq mètres", {"length_ml": 25.0}),
])
def test_mesures_dictees(text, expected):
    r = calc.calculate_from_text(text)
    assert {k: r.inputs[k] for k in expected} == expected


def test_surface_dictee_en_lettres():
    assert calc.calculate_from_text("faux plafond vingt-cinq mètres carrés").to_dict()["steps"][0]["result"] == 25
