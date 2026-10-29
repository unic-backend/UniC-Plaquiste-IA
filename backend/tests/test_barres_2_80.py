"""Règle du patron : au Sénégal, toutes les barres d'ossature (fourrure, cornière, montant, rail) mesurent 2,80 m. Calcul, libellés
des devis, catalogue, fiche méthode et mémoire passent de 2,90 à 2,80 m ; l'identifiant de la barre de fourrure (et son prix) ne
change pas."""
from fastapi.testclient import TestClient

from app import calc, memory, metier
from app.main import app


def test_le_calcul_compte_des_barres_de_2_80():
    assert calc.BAR_LENGTH_M == 2.80 and calc.DEFAULTS["bar_length_m"] == 2.80
    q = {x.sku: x for x in calc.calculate_ceiling(6, 3.7).quantities}
    assert q["UC-BARRE-DE-FOURRURE-2-90-M"].name == "Barre de fourrure (2,80 m)" and q["UC-BARRE-DE-FOURRURE-2-90-M"].quantity == 20
    assert q["UC-CORNIERES"].name == "Cornière de rive (barre de 2,80 m)" and q["UC-CORNIERES"].quantity == 7
    p = {x.sku: x for x in calc.calculate_partition(10, 2.5, 2).quantities}
    assert "2,80 m" in p["MONTANT-M48"].name and "2,80 m" in p["UC-RAILS-48-MM"].name and p["UC-RAILS-48-MM"].quantity == 8


def test_la_barre_de_fourrure_garde_son_identifiant_et_son_prix():
    assert metier.sku_for("Barre de fourrure (2,80 m)") == "UC-BARRE-DE-FOURRURE-2-90-M"
    assert metier.load()["prix_materiaux"]["Barre de fourrure (2,80 m)"] == 1200


def test_anciens_libelles_et_ancienne_regle_corriges_une_fois():
    from app.database import SessionLocal
    from app.models import AppSetting, KnowledgeArticle, Material, Memory
    from app.seed import apply_owner_bars_v8
    with TestClient(app), SessionLocal() as db:
        mat = db.query(Material).filter(Material.sku == "UC-BARRE-DE-FOURRURE-2-90-M").first()
        mat.name, mat.notes = "Barre de fourrure (2,90 m)", "Prix d'une barre de 2,90 m."
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == "methode-ossature").first()
        art.body = "Montants : … Au-delà de 2,90 m de haut : rallonges.\nRails : longueur × 2."
        old = memory.add(db, "Une barre (fourrure, montant, rail, cornière) mesure 2,90 m.", kind="preference", source="user", pinned=True)
        for flag in ("seed_owner_bars_v8", "seed_owner_rules_v12"):
            row = db.get(AppSetting, flag)
            if row:
                db.delete(row)
        db.commit()
        assert apply_owner_bars_v8(db) == 2 and apply_owner_bars_v8(db) == 0                  # une seule fois
        db.refresh(mat)
        db.refresh(art)
        assert mat.name == "Barre de fourrure (2,80 m)" and "2,80 m" in mat.notes
        assert "Barres de 2,80 m : au-delà de 2,80 m de haut, rallonges." in art.body and "2,90" not in art.body
        assert memory.seed_owner_rules(db) == 1
        db.refresh(old)
        assert old.state == "archived"
        active = [m.text for m in db.query(Memory).filter(Memory.state == "active") if "2,80 m" in m.text]
        assert any("mesurent 2,80 m" in t for t in active)
