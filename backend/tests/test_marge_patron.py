"""Règle du patron (marge) : on compte JUSTE (plaques au plan de pose, morceaux comptés en plaques entières), puis, au faux
plafond, on ajoute des PIÈCES, jamais des paquets, aux plaques, aux fourrures et aux cornières : + 10 au-delà de 100 m², + 5 de
50 à 100 m², + 3 en dessous de 50 m². Cloison : aucune marge. Pivots et chevilles à laiton : une par tige, en paquets, sans
marge. Plus de pourcentage de chute (avant : surface × 1,08)."""
import pytest
from fastapi.testclient import TestClient

from app import calc, memory, plan_quote
from app.main import app


def _q(r: calc.CalcResult) -> dict:
    return {q.sku: q.quantity for q in r.quantities}


@pytest.mark.parametrize("surface, pieces", [(12, 3), (49.99, 3), (50, 5), (73, 5), (100, 5), (100.01, 10), (320, 10)])
def test_marge_selon_la_surface(surface, pieces):
    assert calc.margin_pieces(surface) == pieces


def test_plafond_compte_exact_puis_marge_en_pieces():
    r = calc.calculate_ceiling(6.47, 4)                     # 25,88 m² → + 3
    q, laid = _q(r), calc.ceiling_boards(6.47, 4)
    assert laid["plaques"] == 11 and q["BA13-2000x1200"] == 11 + 3          # 9 entières + 2 pour les morceaux, + 3
    assert q["UC-BARRE-DE-FOURRURE-2-90-M"] == 20 + 3 and q["UC-CORNIERES"] == 8 + 3
    tiges = q["UC-TIGES-A-L-UNITE"]                                          # tiges, pivots, chevilles : compte exact
    assert q["UC-PIVOT"] == q["UC-CHEVILLES-A-LETON"] == calc.ceil_int(tiges / 100)
    assert "+ 3 de marge (moins de 50 m²)" in next(x.formula for x in r.quantities if x.sku == "BA13-2000x1200")
    assert any("Marge du patron" in a for a in r.assumptions) and r.to_dict()["verification"]["ok"]


def test_plafond_de_73_m2_et_de_120_m2():
    assert calc.calculate_ceiling(10, 7.3).inputs["marge"] == 5
    big = calc.calculate_ceiling(12, 10)
    assert big.inputs["marge"] == 10 and _q(big)["BA13-2000x1200"] == 50 + 10 and big.to_dict()["verification"]["ok"]


def test_cloison_sans_marge():
    r = calc.calculate_partition(6, 3.5, 2)                  # règle du patron : « non, pas de marge » sur une cloison
    q = _q(r)
    assert q["BA13-2000x1200"] == 20 and q["MONTANT-M48"] == 19 and q["UC-RAILS-48-MM"] == 8 and r.inputs["marge"] == 0
    assert q["UC-VIS-9-MM"] == calc.ceil_int(15 * 4 / 100)                  # vis : compte exact, en paquets
    assert any("Pas de marge sur une cloison" in a for a in r.assumptions) and not any(s.label == "Marge du patron" for s in r.steps)
    assert calc.calculate_partition(40, 3, 2).inputs["marge"] == 0          # 120 m² : toujours rien
    assert _q(calc.calculate_partition_from_area(200, 2))["BA13-2000x1200"] == 167   # ⌈400 / 2,4⌉, sans marge
    assert r.to_dict()["verification"]["ok"]


def test_le_controle_independant_voit_une_marge_oubliee():
    r = calc.calculate_partition(6, 2.5, 2)
    next(x for x in r.quantities if x.sku == "MONTANT-M48").quantity += 3   # marge ajoutée à tort sur une cloison
    assert not calc.verify(r)["ok"]
    r = calc.calculate_ceiling(5, 4)
    next(x for x in r.quantities if x.sku == "UC-CORNIERES").quantity -= 3  # marge oubliée au plafond
    assert not calc.verify(r)["ok"]
    r = calc.calculate_ceiling(5, 4)
    next(x for x in r.quantities if x.sku.startswith("BA13-")).quantity += 6   # plaques au-delà du plan de pose + marge
    assert not calc.verify(r)["ok"]


def test_chute_donnee_par_le_patron_reste_appliquee():
    r = calc.calculate_from_text("faux plafond 5x4 déchet 10 %")
    assert r.inputs["waste"] == 0.10 and _q(r)["BA13-2000x1200"] == calc.ceil_int(9 * 1.10) + 3   # ⌈9 × 1,10⌉ + 3
    assert r.to_dict()["verification"]["ok"]


def test_devis_depuis_un_plan_marge_une_fois_par_article():
    plan = {"pieces": [{"nom": f"Chambre {i}", "surface_m2": 12.0, "longueur_m": 4, "largeur_m": 3, "plafond": "oui"}
                       for i in range(5)] + [{"nom": "Douche", "surface_m2": 4.0, "longueur_m": 2, "largeur_m": 2, "plafond": "oui"}],
            "fichier": "plan.pdf"}
    d = plan_quote.build(plan, hydrofuge_rooms=["douche"], partitions=[{"length_m": 4, "height_m": 2.5}])
    q = {x["sku"]: x["quantity"] for x in d["quantities"]}
    one = calc.ceiling_boards(4, 3)["plaques"]
    # plaques standard : 5 chambres (60 m² de plafond) → + 5 une seule fois ; la cloison au compte exact ; hydrofuges (4 m²) → + 3
    assert q["BA13-2000x1200"] == 5 * one + 5 + calc.wall_boards(4, 2.5, 0.6)["plaques"]
    assert q["BA13-2000x1200-H"] == calc.ceiling_boards(2, 2)["plaques"] + 3
    single = _q(calc.calculate_ceiling(4, 3, margin=False))["UC-CORNIERES"]
    assert q["UC-CORNIERES"] == 5 * single + _q(calc.calculate_ceiling(2, 2, margin=False))["UC-CORNIERES"] + 5   # 64 m² de plafond
    assert q["MONTANT-M48"] == calc.studs_needed(4, 0.6, 1.2, 2.0)                                              # cloison : exact
    assert any(s["label"] == "Marge du patron" for s in d["steps"])


def test_reglage_chute_remis_a_zero_et_fiche_des_plaques_une_fois():
    from app.database import SessionLocal
    from app.models import AppSetting, CompanySettings, KnowledgeArticle, Memory
    from app.seed import apply_owner_margin_v10
    with TestClient(app), SessionLocal() as db:
        co = db.query(CompanySettings).first()
        co.default_waste = 0.08
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == "methode-plaques").first()
        art.body = ("Nombre de plaques = ⌈ surface nette × (1 + déchet) / (largeur plaque × hauteur plaque) ⌉.\n\n"
                    "Valeurs :\n- Plaque BA13\n- Déchet 8 %\nFin.")
        row = db.get(AppSetting, "seed_owner_margin_v10")
        if row:
            db.delete(row)
        db.commit()
        assert apply_owner_margin_v10(db) == 2 and apply_owner_margin_v10(db) == 0     # une seule fois
        db.refresh(co)
        db.refresh(art)
        assert co.default_waste == 0.0
        assert "Marge du patron (faux plafond)" in art.body and "Déchet 8 %" not in art.body and "(1 + déchet)" not in art.body
        assert "Cloison : aucune marge" in art.body
        for flag in ("seed_owner_rules_v16", "seed_owner_rules_v17"):
            row = db.get(AppSetting, flag)
            if row:
                db.delete(row)
        for m in db.query(Memory).filter(Memory.text.like("Marge : %")):
            db.delete(m)
        db.commit()
        assert memory.seed_owner_rules(db) == 2                       # V16 posée puis archivée par V17 (cloisons sans marge)
        active = [m.text for m in db.query(Memory).filter(Memory.state == "active", Memory.text.like("Marge : %"))]
        assert len(active) == 1 and active[0].startswith("Marge : seulement sur le faux plafond") and "Cloison : aucune" in active[0]


def test_fiche_des_plaques_version_10_corrigee_une_fois():
    from app.database import SessionLocal
    from app.models import AppSetting, KnowledgeArticle
    from app.seed import _PLATES_MARGIN_V10, apply_owner_margin_v11
    with TestClient(app), SessionLocal() as db:
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == "methode-plaques").first()
        art.body = "Nombre de plaques = plan de pose.\n" + _PLATES_MARGIN_V10 + "\n\nFin."
        row = db.get(AppSetting, "seed_owner_margin_v11")
        if row:
            db.delete(row)
        db.commit()
        assert apply_owner_margin_v11(db) == 1 and apply_owner_margin_v11(db) == 0     # une seule fois
        db.refresh(art)
        assert "montants, rails)" not in art.body and "Cloison : aucune marge" in art.body and art.body.endswith("Fin.")
