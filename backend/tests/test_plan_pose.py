"""Plan de pose d'un faux plafond (calepinage) dessiné pour les ouvriers : fourrures, tiges et plaques, avec les MÊMES nombres que
le devis ; joints de bout sur une fourrure, joints décalés, pas de lamelle de plaque contre un mur ; alerte si le plan consomme
plus de plaques que le devis."""
import pytest
from fastapi.testclient import TestClient

from app import calc, diagrams, plan_pose as pp
from app.main import app


def _qty(result, sku):
    return next(q.quantity for q in result.quantities if q.sku == sku)


@pytest.mark.parametrize("L, W", [(5, 4), (4, 5), (6, 3.7), (3, 2), (12.4, 8.3), (9, 3), (4.1, 3.3)])
def test_memes_nombres_que_le_devis(L, W):
    d, r = pp.plan(L, W), calc.calculate_ceiling(L, W)
    assert d["tiges"] == _qty(r, "UC-TIGES-A-L-UNITE")
    assert d["plaques_devis"] == _qty(r, calc.board_sku(1.2, 2.0)[0])
    assert d["fourrures"] == next(s.result for s in r.steps if s.label.startswith("Lignes de fourrure"))


def test_plafond_5_par_4():
    d = pp.plan(5, 4)
    assert d["piece"] == [5, 4] and d["fourrures"] == 9 and d["tiges"] == 63 and d["tiges_par_fourrure"] == 7
    assert (d["plaques_entieres"], d["morceaux_coupes"], d["plaques_utilisees"], d["plaques_devis"]) == (6, 4, 9, 9)
    assert "alerte" not in d and "0,50 m" in d["consignes"][0]
    svg = diagrams.sanitize(d["svg"])
    assert "Plan de pose" in svg and "5 m" in svg and "4 m" in svg


@pytest.mark.parametrize("L, W", [(5, 4), (6, 3.7), (9, 3), (12.4, 8.3), (4.1, 3.3), (7, 5)])
def test_pose_dans_les_regles(L, W, monkeypatch):
    seen = {}
    real = pp._svg

    def spy(run_cm, across_cm, lines, per_line, tiles, info):
        seen.update(run=run_cm, across=across_cm, lines=lines, tiles=tiles)
        return real(run_cm, across_cm, lines, per_line, tiles, info)
    monkeypatch.setattr(pp, "_svg", spy)
    pp.plan(L, W)
    tiles, lines = seen["tiles"], set(seen["lines"])
    assert sum(w * h for _, _, w, h, _ in tiles) == seen["run"] * seen["across"]          # tout le plafond, sans chevauchement
    assert all(y in lines and y + h in lines for _, y, _, h, _ in tiles)                 # bouts de plaque sur une fourrure
    assert min(w for _, _, w, _, _ in tiles) >= pp.MIN_PIECE_CM                          # pas de lamelle contre un mur
    rows = sorted({y for _, y, _, _, _ in tiles})
    joints = [{x for x, y, _, _, _ in tiles if y == r} - {0} for r in rows]
    assert all(not (a & b) for a, b in zip(joints, joints[1:]))                          # joints décalés d'une rangée à l'autre


def test_petite_piece_le_plan_previent_quand_le_devis_est_juste():
    d = pp.plan(2.5, 1.5)
    assert d["plaques_utilisees"] == 3 and d["plaques_devis"] == 2
    assert "ajoute 1 plaque" in d["alerte"]


def test_entrees_refusees():
    with pytest.raises(pp.PlanError):
        pp.plan(20, 16)
    with pytest.raises(ValueError):
        pp.plan(0, 4)


def test_l_ia_dessine_le_plan_de_pose():
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("pose_plan", {"length_m": 5, "width_m": 4})
        assert out["tiges"] == 63 and "svg" not in out and len(out["consignes"]) == 4
        assert len(s.images) == 1 and s.images[0]["filename"].endswith(".png")
        assert "error" in s("pose_plan", {"length_m": 30, "width_m": 20})
