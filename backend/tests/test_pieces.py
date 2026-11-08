"""Calcul par pièce SANS l'IA (pieces.py, /api/calc/pieces) et accroche plafond : IPN par éclipses, tiges raccordées (calc.hang_from)."""
import pytest
from fastapi.testclient import TestClient

from app import calc, pieces
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Quotation


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def _q(res: calc.CalcResult, sku: str):
    return next((q for q in res.quantities if q.sku == sku), None)


def test_ipn_eclipses_et_tiges_raccordees():
    """Chantier Oumar : 636 m² sous IPN, suspente de 4 m → 4 tiges de 1 m par point, une éclipse par point (au lieu de la cheville)."""
    res = calc.calculate_ceiling(26.5, 24, dims_known=True)
    points = _q(res, "UC-TIGES-A-L-UNITE").quantity
    calc.hang_from(res, "ipn", 4)
    assert _q(res, "UC-TIGES-A-L-UNITE").quantity == points * 4
    assert _q(res, "UC-CHEVILLES-A-LETON") is None
    assert _q(res, calc.ECLIPSE_SKU).quantity == -(-points // 100)        # paquets de 100, arrondi au-dessus
    assert _q(res, "UC-PIVOT").quantity == -(-points // 100)              # un pivot par point, pas par tige
    assert res.to_dict()["verification"]["ok"]


def test_dalle_suspente_courte_ne_change_rien():
    res = calc.calculate_ceiling(5, 4, dims_known=True)
    before = {q.sku: q.quantity for q in res.quantities}
    calc.hang_from(res, "dalle", 0.6)
    assert {q.sku: q.quantity for q in res.quantities} == before


def test_verification_trouve_une_tige_oubliee():
    res = calc.hang_from(calc.calculate_ceiling(5, 4, dims_known=True), "dalle", 2.5)
    _q(res, "UC-TIGES-A-L-UNITE").quantity -= 1
    assert not res.to_dict()["verification"]["ok"]


def test_pieces_groupees_et_lignes_fusionnees(c):
    rooms = [
        {"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4, "moulure": True},
        {"name": "Chambre", "kind": "ceiling", "length_m": 4, "width_m": 3.5},
        {"name": "SDB", "kind": "ceiling", "length_m": 3, "width_m": 2.5, "hydrofuge": True},
        {"name": "Couloir", "kind": "partition", "length_m": 3, "height_m": 2.6, "doors": 1},
        {"name": "Salon", "kind": "paint", "area_m2": 60},
    ]
    with SessionLocal() as db:
        r = pieces.calculate(db, rooms, labour_m2=2500)
    assert r["ok"]
    assert [b["pieces"] for b in r["blocs"]] == ["Salon, Chambre", "SDB", "Couloir", "Salon"]   # salon + chambre : une seule marge
    keys = [(l["sku"] or l["name"], l["unit"]) for l in r["lignes"]]
    assert len(keys) == len(set(keys))                                                         # chaque matériel une fois
    assert r["surface_posee_m2"] == pytest.approx(20 + 14 + 7.5 + 3 * 2.6)                     # peinture hors pose
    assert r["main_oeuvre"]["montant"] == round(r["surface_posee_m2"] * 2500)
    priced = sum(l["montant"] for l in r["lignes"] if l["montant"] is not None)
    assert r["total"] == round(priced + r["main_oeuvre"]["montant"])
    assert r["complet"] == (not r["prix_manquants"])


@pytest.mark.parametrize("rooms, words", [
    ([], "au moins une pièce"),
    ([{"kind": "toiture"}], "type inconnu"),
    ([{"name": "Salon", "kind": "ceiling", "length_m": 5}], "Largeur manquante pour « Salon »"),
    ([{"kind": "partition", "length_m": 3, "height_m": "abc"}], "Hauteur illisible"),
    ([{"kind": "paint", "area_m2": -4}], "Surface hors limites"),
    ([{"kind": "ceiling", "length_m": float("nan"), "width_m": 3}], "Longueur hors limites"),
])
def test_saisie_refusee_avec_message_clair(c, rooms, words):
    with SessionLocal() as db, pytest.raises(ValueError, match=words):
        pieces.calculate(db, rooms)


def test_api_calcul_puis_devis_sans_ia(c):
    body = {"pieces": [{"name": "Salle de conférence", "kind": "ceiling", "length_m": 26.5, "width_m": 24, "support": "ipn", "suspente_m": 4}],
            "main_oeuvre_m2": 3000}
    r = c.post("/api/calc/pieces", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    eclipse = next(l for l in d["lignes"] if l["sku"] == calc.ECLIPSE_SKU)
    assert eclipse["prix_unitaire"] == 12000 and eclipse["name"] not in d["prix_manquants"]   # prix du patron (grille, 08/11/2026)
    assert c.post("/api/calc/pieces/devis", json=body).status_code == 400     # pas de devis sans client
    r = c.post("/api/calc/pieces/devis", json={**body, "client": "Oumar Pieces", "lieu": "Colobane"})
    assert r.status_code == 200, r.text
    out = r.json()
    with SessionLocal() as db:
        q = db.get(Quotation, out["id"])
        assert q.status == "draft" and q.number == out["numero"]
        assert "faux plafond BA13 salle de conférence (26,5 × 24 m)" in q.object_text
        descs = [i.description for i in q.items]
        assert pieces.LABOUR_LINE in descs and calc.ECLIPSE_NAME in descs
        mo = next(i for i in q.items if i.description == pieces.LABOUR_LINE)
        assert mo.quantity == 636 and mo.unit_price == 3000


def test_api_mesure_invalide_400(c):
    r = c.post("/api/calc/pieces", json={"pieces": [{"kind": "ceiling", "length_m": 5}]})
    assert r.status_code == 400 and "Largeur" in r.json()["detail"]


def test_outil_ia_accroche_ipn(c):
    with SessionLocal() as db:
        out = AgentSession(db, None, {})._t_calculate_materials(kind="ceiling", length_m=10, width_m=8, support="ipn", suspente_m=3)
    skus = {q.get("sku"): q.get("quantity") for q in out["quantites"]}
    assert calc.ECLIPSE_SKU in skus and "UC-CHEVILLES-A-LETON" not in skus
    assert out["verification"]["ok"]


def test_eclipse_du_patron_reprise_avec_son_prix(c):
    """Le patron a déjà ajouté son éclipse à la main (autre code) : elle est reprise, nom et prix gardés, rien n'est dupliqué."""
    from app.models import AppSetting, Material, MaterialPrice
    from app.seed import apply_owner_eclipse_v13
    from app.services import selling_price_for_sku
    with SessionLocal() as db:
        m = db.query(Material).filter(Material.sku == calc.ECLIPSE_SKU).one()
        m.sku, m.name = "UC-ECLIPSE-PATRON", "Éclipse IPN du patron"
        db.add(MaterialPrice(material_id=m.id, kind="selling", amount=12000, currency="FCFA", source="saisie manuelle"))
        db.delete(db.get(AppSetting, "seed_owner_eclipse_v13"))
        db.commit()
        assert apply_owner_eclipse_v13(db) == 1
        mats = db.query(Material).filter(Material.name.ilike("%clipse%")).all()
        assert [(x.sku, x.name) for x in mats] == [(calc.ECLIPSE_SKU, "Éclipse IPN du patron")]
        assert selling_price_for_sku(db, calc.ECLIPSE_SKU)[0] == 12000
        assert apply_owner_eclipse_v13(db) == 0                      # une seule fois
        db.query(MaterialPrice).filter(MaterialPrice.material_id == m.id, MaterialPrice.source == "saisie manuelle").delete()
        db.commit()                                                  # base partagée : on remet la grille comme avant


def test_prix_tranches_par_le_patron_v15(c):
    """Réponses du patron (08/11/2026) : prix appliqués une seule fois, doublons de prix ouverts clos, ancien prix gardé."""
    from app.models import AppSetting, Material, MaterialPrice
    from app.seed import OWNER_PRICES_V15, apply_owner_prices_v15
    from app.services import selling_price_for_sku
    with SessionLocal() as db:
        for sku, amount in (("UC-LAMBRIS-PVC-32-CM", 6000), ("UC-LAMBRIS-PVC-16-CM", 3500), ("UC-COLLE-A-POMPE", 3500)):
            assert selling_price_for_sku(db, sku)[0] == amount, sku   # grille métier
        bande = db.query(Material).filter(Material.sku == "UC-BANDE-A-JOINTS").one()
        before = len(bande.prices)
        db.add_all([MaterialPrice(material_id=bande.id, kind="selling", amount=a, currency="FCFA", source="saisie manuelle") for a in (3000, 5000)])
        db.add(Material(sku="UC-FOURRURES", name="Fourrures", category="ossature", unit="u", waste_coefficient=0.0))
        db.delete(db.get(AppSetting, "seed_owner_prices_v15"))
        db.commit()
        assert apply_owner_prices_v15(db) == len(OWNER_PRICES_V15)
        pack = db.query(Material).filter(Material.sku == "UC-FOURRURES").one()
        assert (pack.name, pack.unit) == ("Paquet de fourrures", "paquet")   # plus confondu avec la barre à 1 200   # base partagée : d'autres tests rejouent les anciennes étapes
        for sku, amount in OWNER_PRICES_V15.items():
            assert selling_price_for_sku(db, sku)[0] == amount, sku
        db.refresh(bande)
        assert [p.amount for p in bande.prices if p.kind == "selling" and p.valid_to is None] == [4000]   # un seul prix ouvert
        assert len(bande.prices) == before + 3                                                        # historique gardé
        assert apply_owner_prices_v15(db) == 0                                                        # une seule fois


def test_memoire_v22_archive_les_prix_contraires(c):
    """Les souvenirs que les prix du patron rendent faux sont archivés (jamais effacés), remplacés quand il le faut."""
    from app import memory as mem
    from app.models import AppSetting, Memory
    with SessionLocal() as db:
        olds = [mem.add(db, t, source="user", pinned=True) for t in (
            "Le prix de l'hydrofuge 2m est de 6000 (et non 5500)", "Éclipse support = 6 000 FCFA le paquet de 100 pièces.")]
        for flag in ("seed_owner_rules_v22", "seed_owner_rules_v23"):   # base partagée : d'autres tests vident la mémoire
            if db.get(AppSetting, flag):
                db.delete(db.get(AppSetting, flag))
        db.commit()
        mem.seed_owner_rules(db)
        assert all(db.get(Memory, m.id).state == "archived" for m in olds)
        active = " ".join(m.text for m in db.query(Memory).filter(Memory.state == "active"))
        assert "le patron raccorde les chutes" in active                    # v23 : fourrures à la longueur totale
        assert "éclipse pour IPN = 12 000" in active and "12 000 FCFA le paquet : deux prix justes" in active and "hydrofuge 2 m = 6 000" not in active and "Colle silicone = 3 500" not in active


def test_vis_au_paquet_de_1000_une_fois_par_chantier(c):
    """Règle du patron : paquet de 1 000 vis. 5 plafonds de 20 m² = 1 500 vis → 2 paquets (pas 5), au prix de sa grille."""
    rooms = [{"name": f"Chambre {i}", "kind": "ceiling", "length_m": 5, "width_m": 4} for i in range(5)]
    with SessionLocal() as db:
        r = pieces.calculate(db, rooms)
    vis = next(l for l in r["lignes"] if l["sku"] == calc.SCREW_PACK_SKU)
    assert vis["quantity"] == 2 and vis["unit"] == "paquet" and "1500 vis" in vis["formula"]
    assert vis["prix_unitaire"] == 5000                                  # « Paquet vis (25 mm ou 35 mm) » de la grille
    assert not any(l["sku"] == "VIS-PLAQUE" for l in r["lignes"])


def test_outil_ia_et_plan_vis_au_paquet(c):
    from app import plan_quote
    with SessionLocal() as db:
        out = AgentSession(db, None, {})._t_calculate_materials(kind="partition", length_m=12, height_m=2.5, sides=1)
    vis = next(q for q in out["quantites"] if q.get("sku") == calc.SCREW_PACK_SKU)
    assert vis["quantity"] == 1 and "450 vis" in vis["formula"]          # 30 m² × 15 = 450 vis → 1 paquet
    plan = plan_quote.build({"pieces": [{"nom": f"Bureau {i}", "surface_m2": 20, "longueur_m": 5, "largeur_m": 4, "plafond": "oui"} for i in range(4)]})
    vis = [q for q in plan["quantities"] if q["sku"] in (calc.SCREW_PACK_SKU, "VIS-PLAQUE")]
    assert [(q["sku"], q["quantity"]) for q in vis] == [(calc.SCREW_PACK_SKU, 2)]   # 4 × 300 = 1 200 vis → 2 paquets


def test_script_de_calcul_pour_claude_code(tmp_path):
    """scripts/unic_calcul.py : le moteur et la grille du patron dans une session Claude Code, sans l'IA."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts" / "unic_calcul.py"
    rooms = '[{"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4}]'
    env = {**os.environ, "UNIC_DATA_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, str(script), rooms, "--main-oeuvre", "4000", "--json"], env=env, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert d["main_oeuvre"]["montant"] == 80000 and d["ok"]
    assert next(x for x in d["lignes"] if x["sku"] == "BA13-2000x1200")["prix_unitaire"] == 4500
    # règle du patron : chutes de fourrure raccordées → ⌈ 45 ml / 2,80 ⌉ = 17, + 3 de marge (et non 18 + 3 ligne par ligne)
    assert next(x for x in d["lignes"] if x["sku"] == "UC-BARRE-DE-FOURRURE-2-90-M")["quantity"] == 20
    dev = subprocess.run([sys.executable, str(script), rooms, "--main-oeuvre", "4000", "--devis", "Awa Fall", "--lieu", "Médina", "--json"],
                         env=env, capture_output=True, text=True, timeout=120)
    assert dev.returncode == 0, dev.stderr
    q = json.loads(dev.stdout)["devis"]
    assert q["numero"].endswith("-AF") and q["pdf"] and Path(q["pdf"]).read_bytes()[:4] == b"%PDF"   # devis brouillon + vrai PDF
    bad = subprocess.run([sys.executable, str(script), '[{"kind": "garage"}]'], env=env, capture_output=True, text=True, timeout=120)
    assert bad.returncode != 0 and "type inconnu" in bad.stderr


def test_script_factures_pour_claude_code(tmp_path):
    """scripts/unic_facture.py : facture brouillon + PDF depuis un devis complet ; refus si des lignes n'ont pas de prix."""
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "scripts"
    env = {**os.environ, "UNIC_DATA_DIR": str(tmp_path)}
    run = lambda *a: subprocess.run([sys.executable, *a], env=env, capture_output=True, text=True, timeout=120)   # noqa: E731
    rooms = '[{"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4}]'
    assert run(str(root / "unic_calcul.py"), rooms, "--devis", "Awa Fall").returncode == 0
    numero = next(l.split()[0] for l in run(str(root / "unic_facture.py"), "liste").stdout.splitlines() if "Awa Fall" in l)
    db = sqlite3.connect(next(tmp_path.rglob("*.db")))
    db.execute("UPDATE quotations SET prices_complete = 0")                         # une ligne sans prix : jamais facturé
    db.commit()
    refus = run(str(root / "unic_facture.py"), "depuis-devis", numero)
    assert refus.returncode != 0 and "sans prix" in refus.stderr
    db.execute("UPDATE quotations SET prices_complete = 1")                         # devis complet (vis, bande, enduit chiffrés)
    db.commit()
    db.close()
    ok = run(str(root / "unic_facture.py"), "depuis-devis", numero)
    assert ok.returncode == 0, ok.stderr
    assert f"{numero}-F" in ok.stdout and Path(ok.stdout.rsplit("PDF : ", 1)[1].strip()).read_bytes()[:4] == b"%PDF"
    assert f"{numero}-F" in run(str(root / "unic_facture.py"), "liste").stdout


def test_bande_au_rouleau_de_150_m_une_fois_par_chantier(c):
    """Règle du patron : rouleau de 150 m à 4 000. Plafond 28 ml + cloison 42 ml = 70 ml → 1 rouleau (pas 1 + 1) ; vis 300 + 395 → 1 paquet."""
    from app import memory as mem
    from app.models import AppSetting, Material, Memory
    from app.seed import apply_owner_tape_v16
    rooms = [{"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4},
             {"name": "Mur", "kind": "partition", "length_m": 6, "height_m": 2.5}]
    with SessionLocal() as db:
        d = pieces.calculate(db, rooms)
        bande = next(l for l in d["lignes"] if l["sku"] == calc.TAPE_ROLL_SKU)
        assert (bande["quantity"], bande["unit"], bande["prix_unitaire"]) == (1, "rouleau", 4000) and "70 ml" in bande["formula"]
        assert next(l for l in d["lignes"] if l["sku"] == calc.SCREW_PACK_SKU)["quantity"] == 1
        assert "Bande à joint" not in d["prix_manquants"]
        assert calc.tape_roll_line(210, "x").quantity == 2
        db.delete(db.get(AppSetting, "seed_owner_tape_v16"))
        db.commit()
        assert apply_owner_tape_v16(db) == 1 and apply_owner_tape_v16(db) == 0
        m = db.query(Material).filter(Material.sku == calc.TAPE_ROLL_SKU).one()
        assert m.unit == "rouleau" and "150 m" in m.name
        if db.get(AppSetting, "seed_owner_rules_v24"):
            db.delete(db.get(AppSetting, "seed_owner_rules_v24"))
            db.commit()
        mem.seed_owner_rules(db)
        assert db.query(Memory).filter(Memory.state == "active", Memory.text.like("Bande à joints : vendue au rouleau de 150 m%")).count() == 1


def test_enduit_au_sac_de_20_kg_une_fois_par_chantier(c):
    """Règle du patron : sac de 20 kg (« Sac enduit », 12 000). Plafond 14 kg + cloison 21 kg = 35 kg → 2 sacs ; devis sans prix manquant."""
    from app.models import AppSetting, Material
    from app.seed import apply_owner_compound_v17
    rooms = [{"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4},
             {"name": "Mur", "kind": "partition", "length_m": 6, "height_m": 2.5}]
    with SessionLocal() as db:
        d = pieces.calculate(db, rooms)
        enduit = next(l for l in d["lignes"] if l["sku"] == calc.COMPOUND_BAG_SKU)
        assert (enduit["quantity"], enduit["unit"], enduit["prix_unitaire"]) == (2, "sac", 12000) and "35 kg" in enduit["formula"]
        assert d["complet"] and d["prix_manquants"] == []
        db.delete(db.get(AppSetting, "seed_owner_compound_v17"))
        db.commit()
        assert apply_owner_compound_v17(db) == 1 and apply_owner_compound_v17(db) == 0
        m = db.query(Material).filter(Material.sku == calc.COMPOUND_BAG_SKU).one()
        assert m.unit == "sac" and "20 kg" in m.name
