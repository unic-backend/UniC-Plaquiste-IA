"""Cas de référence du moteur de calcul : valeurs vérifiées À LA MAIN (calcul posé en commentaire).

Chaque cas fixe aussi les STATUTS : une donnée non fournie n'est jamais « confirmée », une surface nette sans ouvertures
connues n'est qu'« estimée ». Toute régression (formule, arrondi, statut) casse ces tests.
"""
import math
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import calc  # noqa: E402

STD = dict(waste=0.08, board_width=1.2, board_height=2.0, stud_spacing=0.6)


def _status(res, label):
    return next(d["status"] for d in res.to_dict()["data_used"] if d["label"] == label)


def _step(res, prefix):
    return next(s for s in res.to_dict()["steps"] if s["label"].startswith(prefix))


def _qty(res, sku):
    return next(q["quantity"] for q in res.to_dict()["quantities"] if q["sku"] == sku)


def test_case_320m_two_faces_openings_unknown():
    # 320 × 2,50 × 2 = 1 600 m² brut ; ouvertures inconnues → nette = 1 600 « estimée », jamais « confirmée »
    # plaques 1,20 × 2,00 = 2,40 m² : ⌈1 600 × 1,08 / 2,40⌉ = ⌈720⌉ = 720
    # montants : ⌊320 / 0,60⌋ + 1 = 533 + 1 = 534 ; rails : ⌈640 / 2,90⌉ = ⌈220,69⌉ = 221 barres
    r = calc.calculate_partition(320, 2.5, 2, **STD)
    d = r.to_dict()
    assert _step(r, "Surface brute")["result"] == 1600 and _step(r, "Surface brute")["status"] == calc.STATUS_CONFIRMED
    assert _step(r, "Surface des ouvertures")["status"] == calc.STATUS_MISSING
    nette = _step(r, "Surface nette")
    assert nette["result"] == 1600 and nette["status"] == calc.STATUS_ESTIMATED and "sans déduction" in nette["label"]
    assert _status(r, "Ouvertures") == calc.STATUS_MISSING
    assert _qty(r, "BA13-2000x1200") == 720 and _qty(r, "MONTANT-M48") == 534 and _qty(r, "UC-RAILS-48-MM") == 221
    assert any("Ouvertures" in m for m in d["missing"])
    assert any("2.5 m > plaque 2 m" in n for n in d["notes"])
    assert d["verification"]["ok"]


def test_case_small_wall_with_confirmed_door():
    # 4 × 2,50 × 1 = 10 m² ; porte 0,90 × 2,04 = 1,836 m² ; nette = 8,164 m²
    # plaques 1,20 × 2,50 = 3 m² : ⌈8,164 × 1,10 / 3⌉ = ⌈2,993⌉ = 3 ; montants ⌊4/0,6⌋+1 = 7 ; rails ⌈8/2,9⌉ = 3
    r = calc.calculate_partition(4, 2.5, 1, [calc.Opening("door", 0.9, 2.04)], waste=0.10, board_width=1.2,
                                 board_height=2.5, stud_spacing=0.6)
    assert _step(r, "Surface des ouvertures")["result"] == 1.836
    assert _step(r, "Surface nette")["result"] == 8.164 and _step(r, "Surface nette")["status"] == calc.STATUS_CONFIRMED
    assert _status(r, "Ouvertures") == calc.STATUS_CONFIRMED
    assert _qty(r, "BA13-2500x1200") == 3 and _qty(r, "MONTANT-M48") == 7 and _qty(r, "UC-RAILS-48-MM") == 3
    assert r.to_dict()["verification"]["ok"]


def test_unknown_faces_and_default_opening_size_are_assumed_not_confirmed():
    r = calc.calculate_partition(5, 2.5, 2, [calc.Opening("door", 0.9, 2.04, assumed_size=True)], sides_known=False, **STD)
    assert _status(r, "Faces") == calc.STATUS_ASSUMED and _status(r, "Ouvertures") == calc.STATUS_ASSUMED
    assert _step(r, "Surface brute")["status"] == calc.STATUS_ESTIMATED
    a = " ".join(r.assumptions)
    assert "Nombre de faces = 2" in a and "door 0.9×2.04" in a


def test_owner_confirmed_no_openings_is_confirmed():
    r = calc.calculate_partition(6, 2.5, 2, openings_known=True, **STD)
    assert _status(r, "Ouvertures") == calc.STATUS_CONFIRMED and _step(r, "Surface nette")["status"] == calc.STATUS_CONFIRMED
    assert not any("Ouvertures" in m for m in r.missing)


def test_ceiling_from_area_only_is_flagged_as_assumed_square():
    side = math.sqrt(20)
    r = calc.calculate_ceiling(side, side, dims_known=False)
    assert _status(r, "Longueur") == calc.STATUS_ASSUMED
    assert r.assumptions[0].startswith("Pièce supposée carrée") and r.missing[0].startswith("Longueur et largeur réelles")


@pytest.mark.parametrize("kw,msg", [
    (dict(length_m=0, height_m=2.5), "longueur"), (dict(length_m=-3, height_m=2.5), "longueur"),
    (dict(length_m=float("nan"), height_m=2.5), "longueur"), (dict(length_m=5, height_m=float("inf")), "hauteur"),
    (dict(length_m=5000, height_m=3), "Vérifie les unités"),
])
def test_invalid_or_absurd_dimensions_are_refused(kw, msg):
    with pytest.raises(ValueError, match=msg):
        calc.calculate_partition(sides=1, **kw, **STD)


def test_waste_out_of_range_refused():
    with pytest.raises(ValueError, match="chute"):
        calc.calculate_partition(4, 2.5, 1, waste=0.6, board_width=1.2, board_height=2.0, stud_spacing=0.6)


def test_independent_verifier_catches_a_wrong_engine_result():
    r = calc.calculate_partition(10, 2.5, 2, **STD)
    assert calc.verify(r)["ok"]
    r.quantities[0].quantity -= 1   # bug simulé : une plaque de moins
    v = calc.verify(r)
    assert not v["ok"] and "Plaques" in v["problems"][0]


def test_independent_verifier_never_disagrees_on_random_inputs():
    """Fuzz déterministe : 2 000 cloisons et plafonds aléatoires, moteur et contrôle doivent toujours concorder."""
    import random
    rnd = random.Random(42)
    for _ in range(2000):
        ops = [calc.Opening("door", round(rnd.uniform(0.5, 1.5), 2), round(rnd.uniform(1, 2.2), 2), rnd.randint(1, 3))
               for _ in range(rnd.randint(0, 2))]
        try:
            r = calc.calculate_partition(round(rnd.uniform(0.3, 300), 2), round(rnd.uniform(0.5, 6), 2), rnd.choice([1, 2]), ops,
                                         waste=rnd.choice([0, 0.05, 0.08, 0.15]), board_width=rnd.choice([0.6, 1.2]),
                                         board_height=rnd.choice([2.0, 2.5, 3.0]), stud_spacing=rnd.choice([0.4, 0.6]),
                                         confirmed_large=True)
        except ValueError:
            continue
        assert calc.verify(r)["ok"], calc.verify(r)
        c = calc.calculate_ceiling(round(rnd.uniform(0.5, 40), 2), round(rnd.uniform(0.5, 40), 2))
        assert calc.verify(c)["ok"]


def test_agent_tool_marks_omitted_faces_and_blocks_documents_on_bad_verification():
    """Outil de l'IA : faces non dites → « supposé » ; contrôle en échec → aucun devis ni bon créé."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app):
        db = SessionLocal()
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "partition", "length_m": 320, "height_m": 2.5})
        assert out["verification"]["ok"]
        assert any(x.startswith("Faces : 2") and "[assumed]" in x for x in out["donnees"])
        assert any(x.startswith("Ouvertures : inconnues") and "[missing]" in x for x in out["donnees"])
        s.state["last_calc"]["verification"] = {"ok": False, "problems": ["Plaques : moteur 719 ≠ contrôle 720."]}
        err = s("create_purchase_order", {"client_name": "Test"})
        assert "contrôle indépendant" in err["error"]
        db.close()


def test_ai_eval_scoring_is_deterministic_and_catches_invented_data():
    """Banc d'essai IA : la note vient du code. Faces inventées, porte inventée, mm non convertis, devis avant calcul = échecs."""
    from app import evals
    case = {c["id"]: c for c in evals.CASES}
    good = evals.score_case(case["cloison-320"], [("calculate_materials", {"kind": "partition", "length_m": 320, "height_m": 2.5, "sides": 2})])
    assert good["ok"]
    bad = evals.score_case(case["faces-non-dites"], [("calculate_materials", {"kind": "partition", "length_m": 3, "height_m": 2.6, "sides": 2})])
    assert not bad["ok"] and "sides inventé" in bad["problems"][0]
    mm = evals.score_case(case["mm-vers-m"], [("calculate_materials", {"kind": "partition", "length_m": 3500, "height_m": 2500, "sides": 2})])
    assert not mm["ok"]
    door = evals.score_case(case["porte-sans-taille"], [("calculate_materials", {"kind": "partition", "length_m": 4, "height_m": 2.5, "sides": 1,
                                                                                  "openings": [{"kind": "door", "width_m": 0.9}]})])
    assert not door["ok"] and any("inventée" in p for p in door["problems"])
    early = evals.score_case(case["devis-apres-calcul"], [("create_quote", {}), ("calculate_materials",
                                                          {"kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2})])
    assert not early["ok"]
    assert not evals.score_case(case["plafond-surface"], [])["ok"]


def test_ai_eval_run_stores_a_report_without_executing_tools(client=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import evals
    from app.database import SessionLocal

    def fake_complete(messages, tools=None, tool_handler=None, **kw):
        msg = messages[-1]["content"]
        if "320" in msg:
            out = tool_handler("calculate_materials", {"kind": "partition", "length_m": 320, "height_m": 2.5, "sides": 2})
            assert out["evaluation"]   # l'outil n'est pas exécuté
        else:
            tool_handler("calculate_materials", {"kind": "partition", "length_m": 1, "height_m": 1, "sides": 2})
    with TestClient(app) as c:
        db = SessionLocal()
        rep = evals.run(db, cases=evals.CASES[:3], complete=fake_complete)
        db.commit()
        assert rep["total"] == 3 and rep["passed"] == 1 and rep["score"] == 33.3
        got = c.get("/api/evals").json()
        assert got["cases"] == len(evals.CASES) and got["last"]["passed"] == 1 and got["running"] is False
        db.close()
