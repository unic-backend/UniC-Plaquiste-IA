"""Plusieurs pièces, plusieurs cloisons, cotes en centimètres : « salon 5x4 et chambre 4x3 », « 2 cloisons de 3 x 2,5 »,
« plafond en L 4x3 plus 2x2 » ne comptaient que la PREMIÈRE mesure (devis à moitié vide) ; « 400 x 350 cm » donnait 400 m ;
« cloison de 20 m2 » devenait 20 m × 2 m ; « 2 portes » servait de hauteur. Chaque pièce compte maintenant, l'ossature est
calculée pièce par pièce (plaques au plan de pose), paquets et marge du patron sur le total, et le contrôle indépendant refait
tout le calcul."""
import pytest
from fastapi.testclient import TestClient

from app import calc
from app.main import app


def _q(r: calc.CalcResult) -> dict:
    return {q.sku: q.quantity for q in r.quantities}


def _step(r: calc.CalcResult, prefix: str):
    return next(s.result for s in r.steps if s.label.startswith(prefix))


@pytest.mark.parametrize("text, zones", [
    ("faux plafond salon 5x4 et chambre 4x3", [[5, 4], [4, 3]]),
    ("plafond en L 4x3 plus 2x2", [[4, 3], [2, 2]]),
    ("faux plafond 3 pièces de 4x4", [[4, 4]] * 3),
    ("2 chambres de 4x3 en faux plafond", [[4, 3]] * 2),
    ("une chambre de 4x3 et 2 bureaux de 3x3 faux plafond", [[4, 3], [3, 3], [3, 3]]),
    ("salle de bain 3x2 et cuisine 4x3 en faux plafond", [[3, 2], [4, 3]]),
])
def test_chaque_piece_du_plafond_compte(text, zones):
    r = calc.calculate_from_text(text)
    assert r.kind == "ceiling" and r.inputs["zones"] == zones
    assert r.to_dict()["verification"]["ok"]
    singles = [calc.calculate_ceiling(a, b) for a, b in zones]
    assert _step(r, "Surface") == sum(a * b for a, b in zones)
    assert _step(r, "Points d'accroche") == sum(_step(s, "Points d'accroche") for s in singles)   # ossature pièce par pièce
    q = _q(r)
    assert q["UC-TIGES-A-L-UNITE"] == sum(_q(s)["UC-TIGES-A-L-UNITE"] for s in singles)
    assert q["UC-PIVOT"] == calc.ceil_int(q["UC-TIGES-A-L-UNITE"] / 100)                       # paquets sur le total, pas par pièce
    # plaques au plan de pose de chaque pièce ; la marge du patron une seule fois, sur la surface totale
    assert q["BA13-2000x1200"] == (sum(calc.ceiling_boards(a, b)["plaques"] for a, b in zones)
                                   + calc.margin_pieces(sum(a * b for a, b in zones)))


def test_plafond_en_l_signale_la_corniere_du_cote_commun():
    r = calc.calculate_from_text("plafond en L 4x3 plus 2x2")
    assert "2 zones" in r.understanding and "16 m²" in r.understanding
    assert any("côté commun" in a for a in r.assumptions)


@pytest.mark.parametrize("text, walls", [
    ("deux cloisons de 4 m sur 2,5", [[4, 2.5], [4, 2.5]]),
    ("2 cloisons de 3x2.5", [[3, 2.5], [3, 2.5]]),
    ("cloison 4 x 2,5 et 3 x 2,5", [[4, 2.5], [3, 2.5]]),
    ("cloison 3 m + 4 m hauteur 2,5", [[3, 2.5], [4, 2.5]]),
    ("cloisons de 3 m et 4 m, hauteur 2,5", [[3, 2.5], [4, 2.5]]),
    ("2 cloisons de 4 m hauteur 2,6", [[4, 2.6], [4, 2.6]]),
])
def test_chaque_cloison_compte(text, walls):
    r = calc.calculate_from_text(text)
    assert r.kind == "partition" and r.inputs["walls"] == walls
    assert r.to_dict()["verification"]["ok"]
    singles = [calc.calculate_partition(w, h) for w, h in walls]
    assert _step(r, "Nombre de montants") == sum(_step(s, "Nombre de montants") for s in singles)   # montants d'about de chaque cloison
    assert _q(r)["MONTANT-M48"] == sum(_q(s)["MONTANT-M48"] - s.inputs["marge"] for s in singles) + r.inputs["marge"]   # marge 1 fois
    assert _step(r, "Surface brute") == pytest.approx(sum(w * h * 2 for w, h in walls))


def test_une_seule_zone_donne_exactement_l_ancien_calcul():
    for a, b in [(5, 4), (6.3, 4.1), (2.2, 9.7)]:
        assert calc.calculate_ceiling(a, b).to_dict() == calc.calculate_ceiling(a, b, zones=[(a, b)]).to_dict()
        one = calc.calculate_partition(a, 2.6, 2, [calc.Opening("door", 0.9, 2.04)])
        assert one.to_dict() == calc.calculate_partition(a, 2.6, 2, [calc.Opening("door", 0.9, 2.04)], walls=[(a, 2.6)]).to_dict()


def test_le_controle_independant_voit_une_erreur_sur_plusieurs_zones():
    for r in (calc.calculate_ceiling(5, 4, zones=[(5, 4), (4, 3), (2.5, 2.5)]),
              calc.calculate_partition(4, 2.5, walls=[(4, 2.5), (3.2, 2.7), (6, 3.1)])):
        assert r.to_dict()["verification"]["ok"]
        line = next(q for q in r.quantities if q.sku in ("UC-CORNIERES", "MONTANT-M48"))
        line.quantity -= 1
        assert not r.to_dict()["verification"]["ok"]


@pytest.mark.parametrize("text", [
    "faux plafond 5x4 soit 20 m²",                    # la surface redit la même pièce
    "faux plafond 5x4 en dalles 60x60",               # taille de dalle
    "cloison 4x2,5 avec une porte de 90x210",         # taille de porte
    "cloison 4 x 2,5 avec 2 portes de 0,9 x 2,1",
    "cloison 4 m et 2 m de haut",                     # 2 m = la hauteur, pas une cloison de plus
    "cloison 4 m de long et 2,5 m de haut",
    "faux plafond 5 m sur 4 m à 30 cm sous la dalle",
])
def test_une_seule_piece_reste_une_seule_piece(text):
    r = calc.calculate_from_text(text)
    assert "zones" not in r.inputs and "walls" not in r.inputs
    assert r.to_dict()["verification"]["ok"]


def test_taille_de_plaque_jamais_prise_pour_la_cloison():
    r = calc.calculate_from_text("plaques 1200 x 2500 pour cloison 4 x 2,5")
    assert (r.inputs["length_m"], r.inputs["height_m"]) == (4.0, 2.5)


@pytest.mark.parametrize("text, zones", [
    ("faux plafond en plaques 5x4", [[5, 4]]),                                   # « en plaques » : le système, 5x4 la pièce
    ("faux plafond en dalles 60x60 de 5x4", [[5, 4]]),                           # avant : plafond de 60 × 60 m
    ("faux plafond en plaques BA13 salon 5x4 et chambre 4x3", [[5, 4], [4, 3]]),
    ("faux plafond en dalles 600x600 salon 6x5 et bureau 4x3", [[6, 5], [4, 3]]),
])
def test_systeme_de_plafond_et_taille_de_dalle(text, zones):
    r = calc.calculate_from_text(text)
    assert (r.inputs.get("zones") or [[r.inputs["length_m"], r.inputs["width_m"]]]) == zones


@pytest.mark.parametrize("text", ["faux plafond dalles 60x60", "cloison avec porte de 0,9 x 2,1"])
def test_une_taille_de_dalle_ou_de_porte_seule_ne_fait_pas_l_ouvrage(text):
    r = calc.calculate_from_text(text)
    assert not r.quantities and r.missing   # avant : un plafond de 60 × 60 m, une cloison de 0,9 × 2,1 m ; maintenant la question


@pytest.mark.parametrize("text, dims", [
    ("faux plafond 400 x 350 cm", (4.0, 3.5)),        # avant : 400 × 3,5 m
    ("faux plafond 4,5 x 350 cm", (4.5, 3.5)),        # 4,5 est déjà en mètres
    ("cloison 400 x 250 cm", (4.0, 2.5)),
    ("cloison 3500 x 2500 mm", (3.5, 2.5)),
])
def test_cotes_en_centimetres_pour_les_deux_valeurs(text, dims):
    r = calc.calculate_from_text(text)
    keys = ("length_m", "width_m") if r.kind == "ceiling" else ("length_m", "height_m")
    assert tuple(r.inputs[k] for k in keys) == dims


@pytest.mark.parametrize("text, dims, unit", [
    ("faux plafond 450 sur 350", (4.5, 3.5), "centimètres"),   # avant : 157 500 m², refusé
    ("cloison 400 x 250", (4.0, 2.5), "centimètres"),           # avant : « dimensions peu crédibles »
    ("cloison 3500 x 2500", (3.5, 2.5), "millimètres"),
])
def test_cotes_sans_unite_lues_en_cm_ou_mm_et_signalees(text, dims, unit):
    r = calc.calculate_from_text(text)
    keys = ("length_m", "width_m") if r.kind == "ceiling" else ("length_m", "height_m")
    assert tuple(r.inputs[k] for k in keys) == dims
    assert unit in r.assumptions[0] and "à confirmer" in r.assumptions[0]


def test_cloison_donnee_par_sa_surface():
    r = calc.calculate_from_text("cloison de 20 m2")
    assert r.kind == "partition_area" and r.inputs["area_m2"] == 20       # avant : cloison de 20 m × 2 m (le 2 de « m2 »)
    r = calc.calculate_from_text("cloison 20 m² hauteur 2,5")
    assert (r.inputs["length_m"], r.inputs["height_m"]) == (8.0, 2.5) and "Longueur déduite" in r.assumptions[0]
    assert calc.calculate_from_text("doublage 30 m2").inputs["sides"] == 1


def test_un_nombre_de_portes_n_est_pas_une_hauteur():
    r = calc.calculate_from_text("cloison 12 m de long, 2 portes")
    assert r.inputs["height_m"] == 2.5                                     # avant : 2 m (le « 2 » de « 2 portes »)
    assert next(d for d in r.data_used if d["label"] == "Hauteur")["status"] == calc.STATUS_ASSUMED
    assert "Hauteur de la cloison." in r.missing
    assert next(d for d in calc.calculate_from_text("cloison 4 m hauteur 2,5 m").data_used
                if d["label"] == "Hauteur")["status"] == calc.STATUS_CONFIRMED


@pytest.mark.parametrize("text, plenum", [
    ("faux plafond 5x4 avec plénum de 40 cm", 0.4),
    ("faux plafond 5 m sur 4 m à 30 cm sous la dalle", 0.3),
    ("faux plafond 5 x 4 m, descente 50 cm", 0.5),
])
def test_plenum_donne_n_est_plus_demande(text, plenum):
    r = calc.calculate_from_text(text)
    assert r.inputs["plenum_m"] == plenum
    assert not any(m.startswith("Hauteur de plénum") for m in r.missing)
    assert any(d["label"].startswith("Plénum") and d["value"] == plenum for d in r.data_used)


def test_l_ia_calcule_plusieurs_pieces_en_un_seul_appel():
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "ceiling", "zones": [{"length_m": 5, "width_m": 4}, {"length_m": 4, "width_m": 3, "count": 2}]})
        assert "3 zones" in out["compris"] and out["verification"]["ok"]
        assert s.state["last_calc"]["inputs"]["zones"] == [[5, 4], [4, 3], [4, 3]]   # le devis part de TOUTES les pièces
        out = s("calculate_materials", {"kind": "partition", "height_m": 2.5, "sides": 2,
                                        "zones": [{"length_m": 4}, {"length_m": 3, "height_m": 2.7}]})
        assert out["verification"]["ok"] and s.state["last_calc"]["inputs"]["walls"] == [[4, 2.5], [3, 2.7]]
        out = s("calculate_materials", {"kind": "ceiling", "zones": [{"area_m2": 20}]})   # une zone : calcul habituel
        assert "zones" not in s.state["last_calc"]["inputs"] and any("carrée" in h for h in out["hypotheses"])
        assert "error" in s("calculate_materials", {"kind": "partition", "zones": [{"length_m": 4}, {"length_m": 3}]})   # hauteur ?
