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


def test_plan_geometry_check_demotes_doubtful_rooms_and_never_confirms_them():
    """Lecture de plan : cotes incohérentes, hauteur absurde, pièce citée deux fois, unité inconnue → « incertaine », jamais « confirmée »."""
    from app import plans
    data = {"unite_plan": "m", "pieces": [
        {"nom": "Salon", "longueur_m": 5, "largeur_m": 4, "surface_m2": 20, "hauteur_m": 2.6, "plafond": "oui"},          # sain
        {"nom": "Chambre 1", "longueur_m": 4, "largeur_m": 3, "surface_m2": 20, "plafond": "oui"},                          # 4×3=12 ≠ 20
        {"nom": "Bureau", "longueur_m": 3, "largeur_m": 3, "surface_m2": 9, "hauteur_m": 26, "plafond": "oui"},             # 26 m de haut
        {"nom": "Couloir", "longueur_m": 400, "largeur_m": 1.2, "plafond": "oui"},                                          # 400 m : cm lus en m
        {"nom": "Cuisine", "surface_m2": 12, "plafond": "oui"}, {"nom": "cuisine", "surface_m2": 18, "plafond": "oui"},      # deux fois, 12 puis 18
    ]}
    out = plans._clean(data)
    rooms = {r["nom"]: r for r in out["pieces"]}
    assert rooms["Salon"]["confiance"] == "lue" and rooms["Salon"]["plafond"] == "oui"
    for name in ("Chambre 1", "Bureau", "Couloir", "Cuisine", "cuisine"):
        assert rooms[name]["confiance"] == "incertaine" and rooms[name]["plafond"] == "a_confirmer", name
        assert "à confirmer par le patron" in rooms[name]["raison"]
    assert out["total_plafond_confirme_m2"] == 20.0                      # seul le salon est confirmé
    assert set(out["pieces_incertaines"]) == {"Chambre 1", "Bureau", "Couloir", "Cuisine", "cuisine"}
    flat = " | ".join(out["remarques"])
    assert "= 12" in flat and "une des cotes est fausse" in flat and "hauteur 26 m improbable" in flat and "côté de 400 m improbable" in flat and "contradiction" in flat


def test_plan_unknown_unit_only_doubts_surfaces_deduced_from_dimensions():
    from app import plans
    out = plans._clean({"unite_plan": "inconnue", "pieces": [
        {"nom": "A", "surface_m2": 15, "plafond": "oui"}, {"nom": "B", "longueur_m": 5, "largeur_m": 3, "plafond": "oui"}]})
    rooms = {r["nom"]: r for r in out["pieces"]}
    assert rooms["A"]["confiance"] == "surface seule" and rooms["A"]["plafond"] == "oui"        # écrite en m² : indépendante de l'unité
    assert rooms["B"]["confiance"] == "incertaine" and rooms["B"]["plafond"] == "a_confirmer"   # tirée de cotes sans unité
    assert any("Unité du plan inconnue" in r for r in out["remarques"])


def test_quote_margin_uses_only_recorded_purchase_prices():
    """Marge : aucun prix d'achat inventé. Vente à perte signalée ; achat inconnu = non calculable ; seuil choisi par le patron."""
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app import margin
    from app.database import SessionLocal
    from app.main import app
    from app.models import Material, MaterialPrice, Quotation, QuotationItem
    with TestClient(app) as client, SessionLocal() as db:
        mats = []
        for sku, buy in (("MG-OK", 600.0), ("MG-LOSS", 1200.0), ("MG-THIN", 920.0), ("MG-NOBUY", None)):
            m = Material(sku=sku, name=sku, unit="u", category="test")
            db.add(m); db.flush(); mats.append(m)
            if buy is not None:
                db.add(MaterialPrice(material_id=m.id, kind="purchase", amount=buy, valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
        q = Quotation(number="UC-MARGE-1", title="m", status="draft", subtotal=0, total=0)
        db.add(q); db.flush()
        for pos, (m, price, qty) in enumerate(zip(mats, (1000.0, 1000.0, 1000.0, 500.0), (10, 5, 10, 2)), start=1):
            db.add(QuotationItem(quotation_id=q.id, position=pos, description=m.sku, quantity=qty, unit="u", unit_price=price,
                                 total=price * qty, material_id=m.id))
        db.add(QuotationItem(quotation_id=q.id, position=9, description="Main-d'œuvre pose", quantity=1, unit="forfait",
                             unit_price=50000, total=50000))
        db.commit()
        r = margin.analyze(q)
        # vente connue : 10×1000 + 5×1000 + 10×1000 = 25 000 ; achat : 6 000 + 6 000 + 9 200 = 21 200 ; marge 3 800 = 15,2 %
        assert r["marge_connue"] == 3800.0 and r["marge_pct"] == 15.2
        assert [x["ligne"] for x in r["a_perte"]] == ["MG-LOSS"] and "VENTE À PERTE : MG-LOSS" in r["alertes"][0]
        assert r["achat_inconnu"] == ["MG-NOBUY"] and r["hors_catalogue"] == ["Main-d'œuvre pose"]
        assert r["seuil_pct"] is None and r["marge_basse"] == []            # sans seuil du patron : seulement les pertes
        assert margin.analyze(q, min_margin_pct=10)["marge_basse"][0]["ligne"] == "MG-THIN"   # 8 % < 10 %
        assert client.put("/api/settings/margin", json={"min_margin_pct": 100}).status_code == 400
        assert client.put("/api/settings/margin", json={"min_margin_pct": 12}).json()["min_margin_pct"] == 12
        assert client.get(f"/api/quotes/{q.id}/margin").json()["seuil_pct"] == 12
        from app.agent import AgentSession
        out = AgentSession(db, None, {})("quote_margin", {"quote_number": "UC-MARGE-1"})
        assert out["marge_pct"] == 15.2 and out["a_perte"]
        client.put("/api/settings/margin", json={"min_margin_pct": None})
        for it in list(q.items):
            db.delete(it)
        db.delete(q)
        db.query(MaterialPrice).filter(MaterialPrice.material_id.in_([m.id for m in mats])).delete(synchronize_session=False)
        for m in mats:
            db.delete(m)
        db.commit()


def test_partition_from_area_only_is_partial_honest_and_never_becomes_a_quote():
    """« 200 m² de cloison » : plaques, vis, bande, enduit calculés (valeurs vérifiées à la main) ; ossature NON calculée, dite manquante."""
    # 200 m² × 2 faces = 400 m² ; plaques 1,20 × 2,00 = 2,40 m² : ⌈400 × 1,08 / 2,40⌉ = ⌈180⌉ = 180
    r = calc.calculate_partition_from_area(200, 2, waste=0.08, board_width=1.2, board_height=2.0)
    d = r.to_dict()
    assert _qty(r, "BA13-2000x1200") == 180
    assert not any(q["sku"] in ("MONTANT-M48", "UC-RAILS-48-MM") for q in d["quantities"])      # aucune ossature inventée
    assert _step(r, "Montants et rails")["result"] == "non calculable" and _step(r, "Montants et rails")["status"] == calc.STATUS_MISSING
    assert _status(r, "Longueur / hauteur") == calc.STATUS_MISSING and _status(r, "Faces") == calc.STATUS_ASSUMED
    assert any("NE SONT PAS calculés" in m for m in d["missing"]) and d["inputs"]["partial"] and d["verification"]["ok"]
    r.quantities.append(calc.QuantityLine("MONTANT-M48", "Montant", 10, "u"))   # ossature inventée : le vérificateur la refuse
    assert not calc.verify(r)["ok"]


def test_agent_partial_calc_blocks_quotes_unless_the_owner_asks_for_a_partial_one():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app):
        db = SessionLocal()
        s = AgentSession(db, None, {"owner_message": "Fais-moi un devis pour 200 m² de cloison"})
        out = s("calculate_materials", {"kind": "partition", "area_m2": 200})
        assert out["quantites"] and out["verification"]["ok"] and any("[missing]" in x for x in out["donnees"])
        assert "PARTIEL" in s("create_quote", {"client_name": "Awa Ba"})["error"]
        assert "PARTIEL" in s("create_purchase_order", {})["error"]
        # le patron demande explicitement un devis partiel : autorisé
        s.state["owner_message"] = "fais-le quand même, un devis partiel avec seulement les plaques"
        made = s("create_quote", {"client_name": "Partiel Test", "objet": "Cloisons BA13 à Dakar, fourni et posé (plaques seulement).", "lieu": "Dakar", "checks": "client, surface, plaques, TVA vérifiés ; ossature non calculée"})
        assert made.get("numero"), made
        # un calcul complet n'est jamais bloqué
        s2 = AgentSession(db, None, {"owner_message": "bon de commande cloison 6 m x 2,5 m"})
        s2("calculate_materials", {"kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2})
        assert "PARTIEL" not in str(s2("create_purchase_order", {}))
        db.close()


def test_eval_set_covers_the_surface_only_request():
    from app import evals
    case = next(c for c in evals.CASES if c["id"] == "surface-seule")
    good = evals.score_case(case, [("calculate_materials", {"kind": "partition", "area_m2": 200})])
    assert good["ok"]
    bad = evals.score_case(case, [("create_quote", {}), ("calculate_materials", {"kind": "partition", "area_m2": 200, "sides": 2, "length_m": 20})])
    assert not bad["ok"] and len(bad["problems"]) >= 3


def test_bulk_purchase_prices_are_validated_deduplicated_and_feed_the_margin():
    from fastapi.testclient import TestClient
    from app import margin
    from app.database import SessionLocal
    from app.main import app
    from app.models import Material, MaterialPrice, Quotation, QuotationItem
    with TestClient(app) as client, SessionLocal() as db:
        m = Material(sku="BULK-1", name="Bulk test", unit="u", category="test")
        db.add(m); db.flush()
        mid = m.id
        db.commit()
        post = lambda prices, kind="purchase": client.post("/api/materials/prices/bulk", json={"kind": kind, "prices": prices})  # noqa: E731
        assert post([{"id": mid, "amount": 600}]).json() == {"saved": 1, "unchanged": 0, "errors": []}
        assert post([{"id": mid, "amount": 600}]).json()["unchanged"] == 1                     # inchangé : pas de doublon d'historique
        bad = post([{"id": mid, "amount": -5}, {"id": mid, "amount": 0}, {"id": "n-existe-pas", "amount": 10}, {"id": mid, "amount": None}]).json()
        assert bad["saved"] == 0 and len(bad["errors"]) == 3                                   # négatif, nul, inconnu refusés ; vide ignoré
        assert client.post("/api/materials/prices/bulk", json={"kind": "autre", "prices": []}).status_code == 400
        assert post([{"id": mid, "amount": 1000}], kind="selling").json()["saved"] == 1
        assert post([{"id": mid, "amount": 650.5}]).json()["saved"] == 1                         # nouveau prix : remplace l'ancien
        got = next(x for x in client.get("/api/materials").json() if x["id"] == mid)
        assert got["purchase_price"] == 650.5 and got["selling_price"] == 1000
        q = Quotation(number="UC-BULK-1", title="b", status="draft", subtotal=0, total=0)
        db.add(q); db.flush()
        db.add(QuotationItem(quotation_id=q.id, position=1, description="Bulk", quantity=10, unit="u", unit_price=1000, total=10000, material_id=mid))
        db.commit()
        r = margin.analyze(q)
        assert r["marge_connue"] == 3495.0 and r["marge_pct"] == 35.0                          # (1000 − 650,5) × 10 = 3 495 ; 34,95 % -> 35,0
        for it in list(q.items):
            db.delete(it)
        db.delete(q)
        db.query(MaterialPrice).filter(MaterialPrice.material_id == mid).delete()
        db.delete(db.get(Material, mid))
        db.commit()


def test_selling_price_edited_in_the_table_is_used_by_the_next_quote_only():
    """Le tableau « Matériaux & prix » est la référence du chat : un prix modifié sert aux PROCHAINS devis ; un devis déjà fait ne change pas."""
    from fastapi.testclient import TestClient
    from app import services as svc
    from app.database import SessionLocal
    from app.main import app
    from app.models import Material, MaterialPrice, Quotation
    with TestClient(app) as client, SessionLocal() as db:
        m = Material(sku="TAB-1", name="Tableau test", unit="u", category="test")
        db.add(m); db.flush(); mid = m.id; db.commit()
        post = lambda amt: client.post("/api/materials/prices/bulk", json={"kind": "selling", "prices": [{"id": mid, "amount": amt}]}).json()  # noqa: E731
        assert post(1000)["saved"] == 1
        qty = [{"sku": "TAB-1", "name": "Tableau test", "quantity": 3, "unit": "u"}]
        q1 = svc.quotation_from_quantities(db, title="t", quantities=qty, customer_id=None, project_id=None, user_id=None, client_name="Tableau Un")
        db.commit()
        assert q1.items[0].unit_price == 1000 and q1.subtotal == 3000
        assert post(1200)["saved"] == 1                                                  # le patron change le prix dans le tableau
        q2 = svc.quotation_from_quantities(db, title="t", quantities=qty, customer_id=None, project_id=None, user_id=None, client_name="Tableau Deux")
        db.commit()
        assert q2.items[0].unit_price == 1200 and q2.subtotal == 3600                    # le nouveau devis prend le nouveau prix
        assert db.get(Quotation, q1.id).items[0].unit_price == 1000                      # l'ancien devis ne bouge pas
        for q in (q1, q2):
            for it in list(q.items):
                db.delete(it)
            db.delete(q)
        db.query(MaterialPrice).filter(MaterialPrice.material_id == mid).delete()
        db.delete(db.get(Material, mid))
        db.commit()
