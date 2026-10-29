"""Méthode UniC (ratios du patron) : la phrase est lue comme par le calcul. Avant : « 400 x 250 cm » donnait 100 000 m² de mur,
« 4 mètres sur 2 mètres cinquante » 8 m² (le « cinquante » perdu), « cinq mètres sur deux mètres soixante » rien du tout."""
import pytest

from app import metier


@pytest.mark.parametrize("text, wall_m2", [
    ("méthode unic cloison 400 x 250 cm", 10),
    ("méthode unic cloison 4 mètres sur 2 mètres cinquante", 10),
    ("méthode unic cloison cinq mètres sur deux mètres soixante", 13),
    ("méthode unic cloison 5,40 m x 2,50 m, 18 parois", 13.5),
    ("méthode unic 30 m2 deux faces", 30),
])
def test_surface_de_mur_lue_comme_le_calcul(text, wall_m2):
    r = metier.calculate_unic_from_text(text)
    assert r is not None and r.understanding.startswith(f"Hypothèse : {wall_m2:g} m² de mur")
