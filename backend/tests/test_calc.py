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
    assert boards.quantity == 720   # plaque de 2 m par défaut (1600 m² × 1,08 ÷ 2,40 m²)
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
    # 12 m × 2,5 m = 30 m² ; plaque 2,40 m² ; chute 8 % ; entraxe 0,60 m ; barres de 2,90 m
    q = _q(calc.calculate_partition(12, 2.5, 1, []))
    assert q["BA13-2000x1200"] == 14      # ⌈30 × 1,08 / 2,4⌉ = ⌈13,5⌉
    assert q["MONTANT-M48"] == 21         # ⌊12 / 0,6⌋ + 1
    assert q["UC-RAILS-48-MM"] == 9       # ⌈24 / 2,9⌉
    assert q["VIS-PLAQUE"] == 450         # 30 × 15
    assert q["BANDE-JOINT"] == 42.0       # 30 × 1,4
    assert q["ENDUIT-JOINT"] == 21.0      # 30 × 0,35 × 2


def test_real_case_plafond_15m2():
    q = _q(calc.calculate_ceiling(5, 3))
    assert q["BA13-2000x1200"] == 7       # ⌈15 × 1,08 / 2,4⌉ = ⌈6,75⌉


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
