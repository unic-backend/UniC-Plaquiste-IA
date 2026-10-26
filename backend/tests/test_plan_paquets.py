"""Devis depuis un plan : les articles vendus au paquet (pivots, chevilles à laiton, chevilles à frapper, vis 9 mm) sont comptés
sur le total des pièces du plan, puis arrondis une seule fois (avant : arrondi pièce par pièce, trop de paquets)."""
from app import plan_quote

PLAN = {"pieces": [{"nom": f"Chambre {i}", "surface_m2": 12.0, "longueur_m": 4, "largeur_m": 3, "plafond": "oui"} for i in range(5)],
        "fichier": "plan.pdf"}


def _packs(d: dict) -> dict:
    return {q["sku"]: q["quantity"] for q in d["quantities"] if q["unit"] == "paquet"}


def test_paquets_comptes_sur_tout_le_plan():
    d = plan_quote.build(PLAN, partitions=[{"length_m": 4, "height_m": 2.5}, {"length_m": 3, "height_m": 2.5}])
    # 5 plafonds 4 × 3 m : 7 lignes de fourrure × 6 tiges = 42 points chacun → 210 ; avant : 5 paquets (un par pièce)
    # chevilles à frapper : 5 × (⌈14 / 0,5⌉ + 4) + (⌈8 / 0,5⌉ + 2) + (⌈6 / 0,5⌉ + 2) = 160 + 18 + 14 = 192 ; vis 9 : (9 + 7) × 4 = 64
    assert _packs(d) == {"UC-PIVOT": 3, "UC-CHEVILLES-A-LETON": 3, "UC-PAQUET-CHEVILLES-A-FRAPPER": 2, "UC-VIS-9-MM": 1}
    assert any("210 pièces" in q["formula"] for q in d["quantities"] if q["sku"] == "UC-PIVOT")


def test_paquets_du_patron_respectes():
    d = plan_quote.build(PLAN, partitions=[{"length_m": 4, "height_m": 2.5}], fixings={"anchors_per_pack": 50, "screws9_per_pack": 20})
    assert _packs(d)["UC-PAQUET-CHEVILLES-A-FRAPPER"] == 4      # ⌈(160 + 18) / 50⌉
    assert _packs(d)["UC-VIS-9-MM"] == 2                         # ⌈36 / 20⌉
