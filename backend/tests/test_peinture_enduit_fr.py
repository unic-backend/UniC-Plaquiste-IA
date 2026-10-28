"""Peinture et enduit dits comme sur un chantier : « peindre 60 m² » demandait « plafond ou cloison ? » ; « 20 m² et 15 m² »,
« 2 chambres de 12 m² », « 3 murs de 4 x 2,7 » ne comptaient que la première surface ; un lissage était compté comme 10 mm
d'enduit (330 kg pour 30 m²) et « ratissage » n'était pas compris. Cloisons : « avec porte » (sans nombre), « porte standard
90x210 » et « baie vitrée » n'étaient pas déduits ; « sans ouverture » restait « à renseigner »."""
import pytest

from app import calc, orchestrator


@pytest.mark.parametrize("text, area", [
    ("peindre 60 m² en deux couches", 60),
    ("repeindre 45 m2", 45),
    ("peinture 20 m2 et 15 m2", 35),
    ("peinture 2 chambres de 12 m2", 24),
    ("peinture 3 murs de 4 x 2,7", 32.4),
    ("peinture salon 5x4 et chambre 4x3 hauteur 2,7", 86.4),   # murs des deux pièces : 2 × (5+4) × 2,7 + 2 × (4+3) × 2,7
    ("peinture 40 m2 2 couches", 40),                          # « 2 couches » n'est pas une deuxième surface
    ("peinture d'une chambre 4x3 hauteur 2,7", 37.8),
])
def test_surface_a_peindre(text, area):
    r = calc.calculate_from_text(text)
    assert r.kind == "paint" and r.inputs["area_m2"] == pytest.approx(area)


def test_peindre_part_au_calcul_direct():
    assert orchestrator._intent("peindre 60 m² en deux couches", {}) == "calculate"
    assert calc.calculate_from_text("peindre 60 m² en trois couches").inputs["coats"] == 3


def test_plusieurs_surfaces_ecrites_dans_le_detail():
    r = calc.calculate_from_text("peinture salon 5x4 et chambre 4x3 hauteur 2,7")
    assert r.assumptions[0].startswith("Surface = 2 × (5 + 4) × 2.7 + 2 × (4 + 3) × 2.7 = 86.4 m²")


@pytest.mark.parametrize("text, thickness", [
    ("enduit 30 m2", 10),                              # enduit : 10 mm par défaut, comme avant
    ("enduit de lissage 30 m2 2 passes", 2),           # avant : 10 mm (330 kg)
    ("lissage 25 m2", 2),                              # passes non dites : 2, signalé
    ("ratissage 40 m2 trois passes", 3),               # avant : « plafond ou cloison ? »
    ("enduit de finition 30 m2 épaisseur 2", 2),       # l'épaisseur dite prime
])
def test_epaisseur_d_enduit(text, thickness):
    r = calc.calculate_from_text(text)
    assert r.kind == "plaster" and r.inputs["thickness_mm"] == thickness


def test_lissage_signale_comme_ordre_de_grandeur():
    r = calc.calculate_from_text("lissage 25 m2")
    assert "Lissage" in r.assumptions[0] and "non précisé" in r.assumptions[0] and "fiche" in r.assumptions[0]


@pytest.mark.parametrize("text, openings", [
    ("cloison 4x2,5 avec porte", [("door", 0.9, 2.04, 1, True)]),                      # avant : aucune porte (pas de nombre)
    ("cloison 6 x 2,5 avec la porte", [("door", 0.9, 2.04, 1, True)]),
    ("cloison 4x2,5 avec porte standard 90x210", [("door", 0.9, 2.1, 1, False)]),      # avant : taille ignorée
    ("cloison 5 x 2,5 avec une baie vitrée de 3 x 2,2", [("window", 3.0, 2.2, 1, False)]),
    ("cloison 4x2,5 et fenêtre 120x100", [("window", 1.2, 1.0, 1, False)]),
    ("cloison 4x2,5 avec 2 portes et une fenêtre", [("door", 0.9, 2.04, 2, True), ("window", 1.2, 1.2, 1, True)]),
    ("cloison 4x2,5 sans porte", []),
])
def test_portes_et_baies_dites_simplement(text, openings):
    r = calc.calculate_from_text(text)
    assert [(o["kind"], o["width"], o["height"], o["quantity"], o["assumed_size"]) for o in r.inputs["openings"]] == openings
    assert r.to_dict()["verification"]["ok"]


@pytest.mark.parametrize("text", ["cloison 4x2,5 sans ouverture", "cloison 4x2,5 sans porte ni fenêtre", "2 cloisons de 3x2,5 sans ouverture"])
def test_sans_ouverture_n_est_plus_demande(text):
    r = calc.calculate_from_text(text)
    assert not any("Ouvertures" in m for m in r.missing)
    assert next(d for d in r.data_used if d["label"] == "Ouvertures")["status"] == calc.STATUS_CONFIRMED
