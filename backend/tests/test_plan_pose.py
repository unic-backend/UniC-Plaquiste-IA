"""Plan de pose d'un faux plafond (calepinage) dessiné pour les ouvriers, règles du patron : fourrures tous les 50 cm, tiges à
30 cm du mur puis tous les 90 cm, plaques de 2 m en travers (chaque bout sur une fourrure), plaques entières d'un mur à l'autre
et seule la dernière coupée. MÊMES nombres que le devis ; alerte si le plan consomme plus de plaques que le devis."""
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
    assert d["barres_fourrure"] == _qty(r, "UC-BARRE-DE-FOURRURE-2-90-M") and d["cornieres"] == _qty(r, "UC-CORNIERES")
    assert d["plaques_devis"] == _qty(r, calc.board_sku(1.2, 2.0)[0])
    assert d["fourrures"] == next(s.result for s in r.steps if s.label.startswith("Lignes de fourrure"))


def test_plafond_5_par_4():
    d = pp.plan(5, 4)
    assert d["piece"] == [5, 4] and d["fourrures"] == 9 and d["tiges"] == 54 and d["tiges_par_fourrure"] == 6
    assert (d["plaques_entieres"], d["morceaux_coupes"], d["plaques_utilisees"], d["plaques_devis"]) == (8, 2, 9, 9)
    assert "alerte" not in d and "une tous les 50 cm" in d["consignes"][0]
    assert "la première à 30 cm du mur, puis une tous les 90 cm" in d["consignes"][1]
    assert "seule la dernière de chaque rangée est coupée" in d["consignes"][2] and "50 cm × 4 = 2 m" in d["consignes"][2]
    assert "17 barres de 2,80 m" in d["consignes"][0] and d["cornieres"] == 7 and d["plaque"] == "1,20 × 2 m"
    svg = diagrams.sanitize(d["svg"])
    assert "Plan de pose — plafond 5 × 4 m" in svg and "30 cm" in svg and "90 cm" in svg and "50 cm" in svg


def test_exemples_du_patron_seule_la_derniere_plaque_est_coupee():
    six = pp.plan(6, 4)                       # 6 m = 3 plaques de 2 m : aucune coupe
    assert six["morceaux_coupes"] == 0 and six["plaques_entieres"] == 10
    d = pp.plan(6.47, 4)                      # 6,47 m = 3 plaques de 2 m + un morceau de 47 cm
    seen = {}
    real = pp._svg

    def spy(*args):
        seen["tiles"] = args[4]
        return real(*args)
    pp._svg = spy
    try:
        pp.plan(6.47, 4)
    finally:
        pp._svg = real
    assert sorted({h for _, _, _, h, *_ in seen["tiles"]}) == [47, 200] and d["morceaux_coupes"] == 4 + 3
    assert "Plan de pose — plafond 6,47 × 4 m" in d["svg"]


@pytest.mark.parametrize("L, W", [(5, 4), (6, 3.7), (9, 3), (12.4, 8.3), (4.1, 3.3), (7, 5), (6.47, 4)])
def test_pose_dans_les_regles(L, W, monkeypatch):
    seen = {}
    real = pp._svg

    def spy(run_cm, across_cm, lines, ties, tiles, *rest):
        seen.update(run=run_cm, across=across_cm, lines=lines, ties=ties, tiles=tiles)
        return real(run_cm, across_cm, lines, ties, tiles, *rest)
    monkeypatch.setattr(pp, "_svg", spy)
    pp.plan(L, W)
    tiles, lines, ties, run = seen["tiles"], set(seen["lines"]), seen["ties"], seen["run"]
    assert ties == [round(p * 100) for p in calc.hanger_positions(run / 100)]
    assert ties[0] == 30 and all(b - a == 90 for a, b in zip(ties, ties[1:-1]))           # 30 cm du mur, puis tous les 90 cm
    assert 0 < run - ties[-1] <= 50                                                       # toujours une tige près de l'autre mur
    assert sum(w * h for _, _, w, h, *_ in tiles) == run * seen["across"]                  # tout le plafond, sans chevauchement
    assert all(b in lines and b + h in lines for _, b, _, h, *_ in tiles)                 # bouts de plaque (2 m) sur une fourrure
    pw, ph = 120, 200
    assert all((w == pw or a + w == run) and (h == ph or b + h == seen["across"])        # coupe seulement au dernier mur
               for a, b, w, h, *_ in tiles)


@pytest.mark.parametrize("run, ties", [
    (6, [0.3, 1.2, 2.1, 3.0, 3.9, 4.8, 5.7]),       # la dernière à 30 cm du mur : rien à ajouter
    (5, [0.3, 1.2, 2.1, 3.0, 3.9, 4.7]),            # 3,90 est à 1,10 m du mur : une tige de plus à 30 cm du mur
    (6.47, [0.3, 1.2, 2.1, 3.0, 3.9, 4.8, 5.7, 6.17]),
    (0.5, [0.25]),
])
def test_tiges_du_patron(run, ties):
    assert calc.hanger_positions(run) == ties


def test_plaques_comptees_comme_le_patron():
    d = pp.plan(6.47, 4)
    assert "sens des 6,47 m → 3 plaques de 2 m + un morceau de 47 cm" in d["consignes"][3]
    assert "sens des 4 m → 3 rangées de 1,20 m + une rangée de 40 cm" in d["consignes"][3] and "3 × 3 = 9 plaques entières" in d["consignes"][3]
    dec = {x["morceau"]: x for x in d["decoupe"]}
    assert dec["47 × 120 cm"]["nombre"] == 3 and dec["47 × 120 cm"]["par_plaque"] == 4 and dec["47 × 120 cm"]["plaques"] == 1
    assert dec["200 × 40 cm"]["nombre"] == 3 and dec["200 × 40 cm"]["par_plaque"] == 3 and dec["200 × 40 cm"]["plaques"] == 1
    assert dec["47 × 40 cm"]["plaques"] == 0 and dec["47 × 40 cm"]["pris_dans_les_chutes"] == 1   # la 4e chute de 47 × 120
    assert "une plaque en donne 4 → 1 plaque" in d["consignes"][4]
    assert (d["plaques_entieres"], d["plaques_pour_morceaux"], d["plaques_utilisees"]) == (9, 2, 11)
    assert "9 entières + 2 pour les morceaux = 11 plaques" in d["consignes"][5]
    six = pp.plan(6, 4)
    assert six["decoupe"] == [] and "Morceaux (comptés en plaques entières) : aucun." in six["consignes"][4]
    big = pp.plan(6, 3.7)                     # 5 morceaux de 170 × 120 : une plaque n'en donne qu'un → 5 plaques
    assert big["decoupe"] == [{"morceau": "170 × 120 cm", "nombre": 5, "par_plaque": 1, "plaques": 5, "pris_dans_les_chutes": 0}]


@pytest.mark.parametrize("L, W", [(6.47, 4), (6, 4), (5, 4), (3.7, 6)])
def test_trame_60_plaque_dans_le_sens_des_fourrures(L, W, monkeypatch):
    seen = {}
    real = pp._svg

    def spy(run_cm, across_cm, lines, ties, tiles, *rest):
        seen.update(run=run_cm, across=across_cm, lines=lines, ties=ties, tiles=tiles)
        return real(run_cm, across_cm, lines, ties, tiles, *rest)
    monkeypatch.setattr(pp, "_svg", spy)
    d, r = pp.plan(L, W, entraxe_cm=60), calc.calculate_ceiling(L, W, entraxe_cm=60)
    assert d["entraxe_cm"] == 60 and d["tiges"] == _qty(r, "UC-TIGES-A-L-UNITE")                 # mêmes nombres que le devis
    assert d["fourrures"] == next(s.result for s in r.steps if s.label == "Lignes de fourrure (entraxe 0,60 m)")
    ties, lines = seen["ties"], set(seen["lines"])
    assert ties[0] == 30 and all(b - a == 90 for a, b in zip(ties, ties[1:-1]))                   # tiges toujours à 90 cm
    assert sorted(lines)[:3] == [0, 60, 120]                                                       # fourrures tous les 60 cm
    for a, b, w, h, *_ in seen["tiles"]:                                                           # plaque de 1,20 m : 3 fourrures
        if h == 120:
            assert {b, b + 60, b + 120} <= lines
    assert all(b in lines and b + h in lines for _, b, _, h, *_ in seen["tiles"])                 # bords (1,20 m) sur une fourrure
    assert all((w == 200 or a + w == seen["run"]) and (h == 120 or b + h == seen["across"])       # 2 m le long des fourrures
               for a, b, w, h, *_ in seen["tiles"])
    assert "chaque plaque touche 3 fourrures, un bord, le milieu, l'autre bord" in d["consignes"][2]
    assert "une tous les 90 cm" in d["consignes"][1] and "une tous les 60 cm" in d["consignes"][0]


def test_trame_60_comptee_comme_le_patron():
    d = pp.plan(5, 4, entraxe_cm=60)
    assert "sens des 5 m → 2 plaques de 2 m + un morceau de 100 cm" in d["consignes"][3]
    assert "sens des 4 m → 3 rangées de 1,20 m + une rangée de 40 cm ; 2 × 3 = 6 plaques entières" in d["consignes"][3]
    assert [(x["morceau"], x["nombre"], x["par_plaque"], x["plaques"]) for x in d["decoupe"]] == [
        ("100 × 120 cm", 3, 2, 2), ("200 × 40 cm", 2, 3, 1), ("100 × 40 cm", 1, 6, 0)]
    assert d["plaques_utilisees"] == 9 and "Fourrures tous les 60 cm" in d["svg"]
    with pytest.raises(ValueError):
        pp.plan(5, 4, entraxe_cm=55)


def test_barres_de_2_80_et_plaque_de_2_50_si_le_patron_le_dit():
    d = pp.plan(6, 3.7)
    assert d["barres_fourrure"] == 20 and d["cornieres"] == 7          # 54 ml / 2,80 ; périmètre 19,4 ml / 2,80
    assert "20 barres de 2,80 m" in d["consignes"][0] and "Plaques de 2 m" in d["consignes"][2]
    big = pp.plan(5, 4, board_height=2.5)
    assert big["plaque"] == "1,20 × 2,50 m" and "Plaques de 2,50 m" in big["consignes"][2] and "50 cm × 5 = 2,50 m" in big["consignes"][2]
    assert big["plaques_devis"] == 8 and big["plaques_utilisees"] == 9 and "ajoute 1 plaque" in big["alerte"]


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
        assert out["tiges"] == 54 and "svg" not in out and len(out["consignes"]) == 7 and out["plaque"] == "1,20 × 2 m"
        assert len(s.images) == 1 and s.images[0]["filename"].endswith(".png")
        assert s("pose_plan", {"length_m": 5, "width_m": 4, "plaque_m": 2.5})["plaque"] == "1,20 × 2,50 m"   # 2,50 seulement si dit
        assert s("pose_plan", {"length_m": 5, "width_m": 4, "entraxe_cm": 60})["tiges"] == 48                # 8 fourrures × 6 tiges
        calc_out = s("calculate_materials", {"kind": "ceiling", "length_m": 5, "width_m": 4, "entraxe_cm": 60})
        assert "entraxe 0,60 m" in str(calc_out) and "48" in str(calc_out)
        assert "error" in s("pose_plan", {"length_m": 30, "width_m": 20})
