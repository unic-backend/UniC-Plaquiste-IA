"""Moulures de plafond avec les règles du patron : barres de 3 m (⌈ longueur / 3 ⌉), 1 colle pour 5 barres (silicone par défaut,
à pompe si demandée). Avant : règles connues en mémoire mais aucun calcul ; « moulure salon 5x4 » partait en faux plafond."""
import pytest
from fastapi.testclient import TestClient

from app import calc
from app.main import app


def _q(r):
    return {q.sku: q.quantity for q in r.quantities}


@pytest.mark.parametrize("text, ml, bars, glue_sku, glues, taille", [
    ("moulure salon 5x4", 18, 6, "UC-COLLE-SILICONE", 2, 4),                     # 2 × (5 + 4) = 18 ml
    ("moulure 18 ml taille 2", 18, 6, "UC-COLLE-SILICONE", 2, 2),
    ("moulure 2 chambres de 4x3 colle à pompe", 28, 10, "UC-COLLE-A-POMPE", 2, 4),
    ("corniche 25 m", 25, 9, "UC-COLLE-SILICONE", 2, 4),                          # ⌈ 25 / 3 ⌉ = 9 barres
    ("moulure plafond 6 x 5 taille 4", 22, 8, "UC-COLLE-SILICONE", 2, 4),
    ("moulure 31 ml", 31, 11, "UC-COLLE-SILICONE", 3, 4),                         # ⌈ 11 / 5 ⌉ = 3 colles
])
def test_moulure_regles_du_patron(text, ml, bars, glue_sku, glues, taille):
    r = calc.calculate_from_text(text)
    assert r.kind == "moulure" and r.inputs["length_ml"] == ml
    q = _q(r)
    assert q[f"UC-MOULURE-TAILLE-{taille}-BARRE-DE-3-M"] == bars and q[glue_sku] == glues
    assert r.to_dict()["verification"]["ok"]


def test_taille_non_dite_supposee_et_signalee():
    r = calc.calculate_from_text("moulure salon 5x4")
    assert "Taille de moulure (2 ou 4)." in r.missing and any("taille 4 supposée" in a for a in r.assumptions)
    assert not calc.calculate_from_text("moulure salon 5x4 taille 2").missing


def test_faux_plafond_avec_moulure():
    r = calc.calculate_from_text("faux plafond salon 5x4 et chambre 4x3 avec moulure taille 2")
    q = _q(r)
    assert r.kind == "ceiling" and q["UC-MOULURE-TAILLE-2-BARRE-DE-3-M"] == 11 and q["UC-COLLE-SILICONE"] == 3   # 18 + 14 = 32 ml
    assert q["UC-TIGES-A-L-UNITE"] > 0 and r.to_dict()["verification"]["ok"]
    assert not any("MOULURE" in s for s in _q(calc.calculate_from_text("faux plafond 5x4")))   # pas demandée : pas ajoutée


def test_le_controle_independant_voit_une_erreur_de_moulure():
    r = calc.calculate_moulure(18)
    next(q for q in r.quantities if "MOULURE" in q.sku).quantity = 5
    assert not r.to_dict()["verification"]["ok"]


def test_moulure_sans_longueur_demande_la_mesure():
    r = calc.calculate_from_text("moulure")
    assert not r.quantities and "Longueur à couvrir" in r.missing[0]


def test_l_ia_calcule_les_moulures_et_le_devis_a_les_prix_du_patron():
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "moulure", "length_m": 5, "width_m": 4, "moulure_taille": 2})
        assert out["verification"]["ok"] and s.state["last_calc"]["inputs"]["length_ml"] == 18
        out = s("calculate_materials", {"kind": "ceiling", "length_m": 5, "width_m": 4, "with_moulure": True, "colle": "pompe"})
        skus = {q["sku"]: q["quantity"] for q in out["quantites"]}
        assert skus["UC-MOULURE-TAILLE-4-BARRE-DE-3-M"] == 6 and skus["UC-COLLE-A-POMPE"] == 2 and out["verification"]["ok"]
        quote = s("create_quote", {"client_name": "Awa Fall", "checks": "client, dimensions 5x4 et moulure vérifiés",
                                   "objet": "Fourniture et pose de faux plafond BA13 avec moulure."})
        from app.models import Quotation, QuotationItem
        qid = db.query(Quotation).filter(Quotation.number == quote["numero"]).one().id
        prices = {i.description: i.unit_price for i in db.query(QuotationItem).filter(QuotationItem.quotation_id == qid)}
        assert prices["Moulure taille 4 (barre de 3 m)"] == 3500 and prices["Colle à pompe"] == 3500   # prix donnés par le patron
