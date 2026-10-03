from app.calc import (
    Opening,
    boards_needed,
    calculate_from_text,
    calculate_paint,
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
    assert boards.quantity == 576
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
