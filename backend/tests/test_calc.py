import pytest

from app import calc
from app.calc import (
    Opening,
    boards_needed,
    calculate_from_text,
    calculate_partition,
    calculate_surface,
    parse_number,
    partition_area,
    studs_needed,
)


def test_partition_area_example_from_spec():
    # 320 m × 2.50 m × 2 faces = 1 600 m²
    areas = partition_area(320, 2.50, sides=2)
    assert areas["gross"] == 1600.0
    assert areas["net"] == 1600.0


def test_boards_needed_exact():
    # 25 m², 8% waste, 3 m² board → 25*1.08/3 = 9.0 → 9
    assert boards_needed(25.0, 0.08, 3.0) == 9
    assert boards_needed(1600.0, 0.08, 3.0) == 576


def test_studs():
    assert studs_needed(12.0, 0.60) == 21  # 12/0.6 + 1


def test_openings_deducted():
    areas = partition_area(10, 2.5, sides=1, openings=[Opening("door", 0.90, 2.04, 1)])
    assert abs(areas["net"] - (25 - 1.836)) < 1e-6


def test_parse_french_numbers():
    assert parse_number("2,50") == 2.5
    assert parse_number("1 600") == 1600.0
    assert parse_number("12.5") == 12.5


def test_from_text_partition_spec_example():
    r = calculate_from_text("cloison 320 m x 2,50 m deux faces")
    assert r is not None
    assert r.kind == "partition"
    brute = next(s for s in r.steps if s.label == "Surface brute")
    assert brute.result == 1600.0
    boards = next(q for q in r.quantities if q.sku.startswith("BA13"))
    assert boards.quantity == 668   # plan de pose (plaque de 2 m) : 532 entières + 136 pour les morceaux ; cloison : pas de marge
    assert any("prix" in m.lower() for m in r.missing)


def test_from_text_paint():
    r = calculate_from_text("peinture 1600 m² deux couches")
    assert r is not None
    assert r.kind == "paint"
    paint = next(q for q in r.quantities if q.sku == "PEINTURE")
    assert paint.quantity == 320.0  # 1600*2*0.10


def test_surface():
    r = calculate_surface(12, 2.5)
    assert r.steps[0].result == 30.0


def test_never_hides_formula():
    r = calculate_partition(12, 2.5, sides=2)
    assert all(s.formula for s in r.steps)
    assert r.assumptions
    assert r.missing


def _q(res):
    return {q["sku"]: q["quantity"] for q in res.to_dict()["quantities"]}


def test_real_case_cloison_30m2_one_face():
    # 12 m × 2,5 m = 30 m² ; plaque 1,20 × 2 m debout ; entraxe 0,60 m ; barres de 2,80 m ; cloison : pas de marge (règle du patron)
    q = _q(calc.calculate_partition(12, 2.5, 1, []))
    assert q["BA13-2000x1200"] == 13      # 10 entières + 10 morceaux de 50 × 120 (4 par plaque → 3)
    assert q["MONTANT-M48"] == 30         # ⌈12 / 0,6⌉ + 1 = 21, + 9 jonctions doublées (règle du patron)
    assert q["UC-RAILS-48-MM"] == 9       # ⌈24 / 2,8⌉
    assert q["VIS-PLAQUE"] == 450         # 30 × 15
    assert q["BANDE-JOINT"] == 42.0       # 30 × 1,4
    assert q["ENDUIT-JOINT"] == 21.0      # 30 × 0,35 × 2


def test_real_case_plafond_15m2():
    q = _q(calc.calculate_ceiling(5, 3))
    assert q["BA13-2000x1200"] == 7 + 3   # plan de pose : 4 entières + 3 pour les morceaux ; + 3 de marge (moins de 50 m²)


def test_real_case_paint_and_plaster():
    p = _q(calc.calculate_paint(30))
    assert p["PEINTURE"] == 6.0 and p["IMPRESSION"] == 2.4   # 30 × 0,10 × 2 couches ; 30 × 0,08
    assert _q(calc.calculate_plaster(20))["ENDUIT"] == 220.0  # 20 m² × 10 mm × 1,10


def test_stud_count_not_hit_by_float_error():
    assert calc.studs_needed(0.7, 0.1) == 8   # 0,7 / 0,1 = 6,999… en flottant


@pytest.mark.parametrize("fn,args", [
    (calc.calculate_partition, (-5, 2.5)), (calc.calculate_partition, (0, 2.5)), (calc.calculate_partition, (5, 0)),
    (calc.calculate_ceiling, (-3, 4)), (calc.calculate_ceiling, (3, 0)),
    (calc.calculate_paint, (-10,)), (calc.calculate_plaster, (0,)), (calc.calculate_surface, (-2, 3)),
    (calc.calculate_partition, (float("nan"), 2.5)),
])
def test_impossible_inputs_rejected(fn, args):
    with pytest.raises(ValueError):
        fn(*args)


def test_huge_surface_needs_confirmation():
    with pytest.raises(ValueError, match="Vérifie les unités"):
        calc.calculate_partition(5000, 3, 1)           # 15 000 m²
    assert calc.calculate_partition(5000, 3, 1, confirmed_large=True)
    assert calc.calculate_partition(320, 2.5, 2)       # exemple de la spec : 1 600 m², accepté


def test_waste_out_of_range_rejected():
    with pytest.raises(ValueError):
        calc.calculate_partition(5, 2.5, waste=0.9)


def test_engine_agrees_with_the_independent_exact_verifier_on_thousands_of_random_jobs():
    """Cloisons, plafonds et phrases au hasard (graine fixe) : le moteur ne plante pas et le vérificateur indépendant (fractions exactes)
    ne trouve aucune différence. Une entrée invalide doit être REFUSÉE proprement (ValueError), jamais donner un faux chiffre."""
    import random
    rnd = random.Random(7)
    checked = refused = 0
    for _ in range(500):
        ops = [Opening(kind="porte", width=round(rnd.uniform(0.6, 1.5), 2), height=round(rnd.uniform(1.8, 2.4), 2), quantity=rnd.randint(1, 3))
               for _ in range(rnd.randint(0, 3))]
        try:
            r = calc.calculate_partition(round(rnd.choice([0.4, 1, 2.5, 3.3, 7.77, 12, 25.5, 40, 80]) * rnd.uniform(0.5, 1.5), 2),
                                         round(rnd.choice([2.2, 2.5, 2.7, 3, 3.6, 4.5]) * rnd.uniform(0.8, 1.2), 2), rnd.choice([1, 2]), ops,
                                         waste=rnd.choice([0, 0.05, 0.08, 0.1, 0.15]), confirmed_large=True)
        except ValueError:
            refused += 1
            continue
        assert calc.verify(r)["problems"] == [], r.inputs
        checked += 1
    for _ in range(300):
        try:
            r = calc.calculate_ceiling(round(rnd.uniform(1, 30), 2), round(rnd.uniform(1, 20), 2), waste=rnd.choice([0, 0.08, 0.12]), confirmed_large=True)
        except ValueError:
            refused += 1
            continue
        assert calc.verify(r)["problems"] == [], r.inputs
        checked += 1
    words = ["cloison", "faux plafond", "plafond", "peinture", "enduit", "12 m2", "5x4", "4,5 m", "hauteur 2,7", "longueur 8", "deux faces",
             "une face", "porte", "fenêtre", "BA13", "10 m²", "3 m par 4", "0", "-3", "1e9", "abc", "30m2 de cloison hauteur 2.5"]
    for _ in range(600):
        text = " ".join(rnd.sample(words, rnd.randint(1, 5)))
        try:
            r = calculate_from_text(text)
        except ValueError:
            refused += 1
            continue
        if r is not None:
            assert calc.verify(r)["problems"] == [], text
            checked += 1
    assert checked > 700 and refused >= 1                                                     # beaucoup de cas vérifiés ; l'invalide est bien refusé


def test_peinture_murs_d_une_piece_utilise_le_perimetre():
    r = calc.calculate_from_text("peinture murs salon 5x4 hauteur 2.5")
    assert r.inputs["area_m2"] == 45.0
    assert "murs de la pièce" in r.assumptions[0]


def test_peinture_deux_dimensions_sans_hauteur_est_signalee():
    r = calc.calculate_from_text("peinture 5x4")
    assert r.inputs["area_m2"] == 20.0
    assert "hauteur" in r.assumptions[0]


def test_dimension_negative_refusee():
    import pytest
    with pytest.raises(ValueError):
        calc.calculate_from_text("cloison -5 x 3")


def test_troisieme_valeur_signalee():
    r = calc.calculate_from_text("cloison 3m x 2,5m x 4")
    assert any("Trois valeurs" in m for m in r.missing)


def test_couches_en_toutes_lettres():
    assert calc.calculate_from_text("peinture 40 m2 une couche").inputs["coats"] == 1
    assert calc.calculate_from_text("peinture 40 m2 trois couches").inputs["coats"] == 3
    assert calc.calculate_from_text("peinture 40 m2 double couche").inputs["coats"] == 2
    assert calc.calculate_from_text("peinture 40 m2 3 couches").inputs["coats"] == 3


def test_millimetres_convertis_dans_la_phrase():
    r = calc.calculate_from_text("cloison 3500 mm par 2500 mm double face")
    assert r.inputs["length_m"] == 3.5 and r.inputs["height_m"] == 2.5


def test_plafond_depuis_une_surface_signale_la_forme_supposee():
    r = calc.calculate_from_text("faux plafond 25 m²")
    assert "supposée carrée" in r.assumptions[0]


def test_montants_du_patron_deux_montants_a_chaque_jonction():
    # règle du patron : un montant tous les 60 cm (ou 50), premier et dernier contre le mur ; 2 côte à côte à chaque jonction
    assert calc.studs_needed(6.0, 0.6, 1.2, 2.0) == 15     # son exemple : 11 + 4 jonctions
    assert calc.studs_needed(5.0, 0.6, 1.2) == 14          # ⌈5 / 0,6⌉ + 1 = 10, + 4 jonctions (plaques de 1,20 debout)
    assert calc.studs_needed(4.8, 0.6, 1.2) == 12          # 4 plaques pile : 9 + 3 jonctions
    assert calc.studs_needed(6.0, 0.5, 1.2, 2.0) == 15     # 50 cm : plaques couchées de 2 m → 13 + 2 jonctions
    assert calc.studs_needed(5.0, 0.5, 1.2) == 11          # sans longueur de plaque connue : la grille seule
    r = calc.calculate_partition(5, 2.5, 2)
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 14 and calc.verify(r)["ok"]
    q = {x.sku: x for x in calc.calculate_partition(6, 2.5, 2).quantities}["MONTANT-M48"]
    assert q.quantity == 15 and "2 côte à côte" in q.formula and "tous les 1,2 m, plaque debout" in q.formula
    r = calc.calculate_partition(6, 2.5, 2, stud_spacing=0.5)
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 15 and calc.verify(r)["ok"]


def test_cloison_en_l_chaque_cote_a_ses_montants_d_about():
    # règle du patron : cloison en L = un mur par côté ; l'angle a déjà 2 montants (le bout de chaque mur), rien à ajouter
    r = calc.calculate_partition(4, 2.5, 2, walls=[(4, 2.5), (3, 2.5)])
    assert {x.sku: x.quantity for x in r.quantities}["MONTANT-M48"] == 11 + 8 and calc.verify(r)["ok"]   # (8 + 3) + (6 + 2)


def test_montants_plus_hauts_qu_une_barre():
    # 3,20 m : une barre de 2,80 m par montant + rallonges de 0,40 m (7 par barre) → 11 + ⌈11/7⌉ = 13 ; 14 + ⌈14/7⌉ = 16
    # 5,80 m : deux barres par montant + rallonges de 0,20 m (14 par barre) → 22 + ⌈11/14⌉ = 23
    assert calc.stud_bars(11, 3.2) == 13
    assert calc.stud_bars(11, 2.5) == 11 and calc.stud_bars(11, 5.8) == 23 and calc.stud_bars(11, 2.8) == 11
    r = calc.calculate_partition(5, 3.2, 2)
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 16 and calc.verify(r)["ok"]


@pytest.mark.parametrize("h, splices", [(2.5, (0, 0.0)), (2.8, (0, 0.0)), (3.5, (1, 0.7)), (5.6, (1, 0.0)), (6.0, (2, 0.4))])
def test_raccords_de_montant(h, splices):
    assert calc.stud_splices(h) == splices


def test_cloison_haute_rallonges_et_eclisses_au_devis():
    # 6 × 3,50 m : 15 montants = 15 barres + 15 rallonges de 70 cm (4 par barre → 4) = 19 ; rails 5 + éclisses ⌈15 / 7⌉ = 3
    r = calc.calculate_partition(6, 3.5, 2)
    q = {x.sku: x for x in r.quantities}
    assert q["MONTANT-M48"].quantity == 19 and "1 rallonge de 70 cm" in q["MONTANT-M48"].notes
    assert "rail de 40 cm" in q["MONTANT-M48"].notes
    assert q["UC-RAILS-48-MM"].quantity == 8 and "éclisses : 15 morceaux de 40 cm, 7 par barre → 3" in q["UC-RAILS-48-MM"].formula
    assert calc.verify(r)["ok"]
    assert {x.sku: x.quantity for x in calc.calculate_partition(6, 2.5, 2).quantities}["UC-RAILS-48-MM"] == 5   # pas de raccord


def test_plafond_compte_la_corniere_de_rive():
    # 4 × 5 m : périmètre 18 ml → ⌈18 / 2,80⌉ = 7 barres de cornière, + 3 de marge (moins de 50 m²)
    r = calc.calculate_ceiling(4, 5)
    q = {x.sku: x.quantity for x in r.quantities}
    assert q["UC-CORNIERES"] == 7 + 3 and calc.verify(r)["ok"]


def test_trois_montants_de_renfort_par_porte():
    # 6 m : 15 montants (11 + 4 jonctions doublées) ; 2 portes → + 2 × 3 = 21 (règle UniC)
    r = calc.calculate_partition(6, 2.7, 2, [calc.Opening("door", 0.9, 2.04, 2)])
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 21 and calc.verify(r)["ok"]
    r = calc.calculate_partition(6, 2.7, 2, [calc.Opening("window", 1.2, 1.2, 1)])
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 15      # fenêtre : pas de renfort automatique


def test_portes_en_toutes_lettres_et_taille_supposee():
    r = calc.calculate_from_text("cloison 6 x 2.7 avec une porte")
    assert [(o["kind"], o["quantity"], o["assumed_size"]) for o in r.inputs["openings"]] == [("door", 1, True)]
    assert {q.sku: q.quantity for q in r.quantities}["MONTANT-M48"] == 18   # 15 + 3 de renfort
    r = calc.calculate_from_text("cloison 6 x 2.7 avec deux portes et une fenêtre")
    assert [(o["kind"], o["quantity"]) for o in r.inputs["openings"]] == [("door", 2), ("window", 1)]
