"""Calculs d'affaires exacts (repris d'ARENA) : valeurs vérifiées à la main, entrées invalides refusées, somme d'échéancier exacte."""
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import business_calc as bc  # noqa: E402


def test_marge_by_hand():
    r = bc.marge(1_000_000, {"matériaux": 600_000, "main d'œuvre": 250_000})
    assert r["valide"] and r["cout_total"] == 850_000 and r["marge"] == 150_000 and r["marge_pct"] == 15.0 and not r["a_perte"]
    assert bc.marge(100, {"x": 150})["a_perte"] is True


@pytest.mark.parametrize("rev,couts", [(0, {"a": 1}), (-5, {"a": 1}), (None, {"a": 1}), (100, {}), (100, None), (100, {"a": -1}), (100, {"a": "abc"}), (True, {"a": 1}), (float("nan"), {"a": 1})])
def test_marge_refuses_bad_input_instead_of_returning_a_misleading_number(rev, couts):
    r = bc.marge(rev, couts)
    assert r["valide"] is False and r["raison"]


def test_echeancier_classic_50_30_20():
    r = bc.echeancier(1_000_000, [("Acompte", 50), ("Avancement", 30), ("Solde", 20)])
    assert r["valide"] and [e["montant"] for e in r["etapes"]] == [500_000, 300_000, 200_000] and r["somme_exacte"]


def test_echeancier_sum_is_always_exact_even_when_rounding_would_lose_a_franc():
    # 100 FCFA en 33,34 / 33,33 / 33,33 : arrondir chaque étape donnerait 33+33+33 = 99
    r = bc.echeancier(100, [("A", 33.34), ("B", 33.33), ("C", 33.33)])
    assert sum(e["montant"] for e in r["etapes"]) == 100 and r["somme_exacte"]
    r = bc.echeancier(1_000_001, [("A", 33.3), ("B", 33.3), ("C", 33.4)])          # total impair, tiers
    assert sum(e["montant"] for e in r["etapes"]) == 1_000_001
    assert all(isinstance(e["montant"], int) for e in r["etapes"])                 # FCFA entiers


def test_echeancier_tolerance_and_refusals():
    ok = bc.echeancier(1000, [("A", 50), ("B", 49.7)])                              # 99,7 % : toléré, normalisé
    assert ok["valide"] and sum(e["montant"] for e in ok["etapes"]) == 1000
    for bad in ([("A", 50), ("B", 40)], [("A", 60), ("B", 60)], [], None, [("A", 0), ("B", 100)], [("A", "x"), ("B", 100)]):
        assert bc.echeancier(1000, bad)["valide"] is False
    assert bc.echeancier(0, [("A", 100)])["valide"] is False
    assert bc.echeancier(100.5, [("A", 50), ("B", 50)])["etapes"][0]["montant"] == 50.25    # total décimal : centimes


def test_echeancier_accepts_dict_steps_like_the_ai_sends_them():
    r = bc.echeancier(600, [{"libelle": "Acompte", "pourcentage": 40}, {"libelle": "Solde", "pourcentage": 60}])
    assert [e["montant"] for e in r["etapes"]] == [240, 360]


def test_delai_counts_the_known_delay_risk():
    ok = bc.delai(30, 20, 5)
    assert ok["marge_jours"] == 5 and ok["tenable"] is True
    ko = bc.delai(30, 25, 10)
    assert ko["marge_jours"] == -5 and ko["tenable"] is False
    assert bc.delai(0, 10)["valide"] is False and bc.delai(10, -1)["valide"] is False and bc.delai(10, 5, -3)["jours_risque"] == 0


def test_comparer_what_if_gives_the_gap_to_the_base():
    r = bc.comparer({"revenu": 1_000_000, "couts": {"a": 700_000}},
                    [{"nom": "Plaques +10 %", "revenu": 1_000_000, "couts": {"a": 770_000}},
                     {"nom": "Prix +5 %", "revenu": 1_050_000, "couts": {"a": 700_000}, "jours_disponibles": 20, "jours_estimes": 15}])
    assert r["valide"]
    v1, v2 = r["variantes"]
    assert v1["ecart_marge"] == -70_000 and v1["ecart_pct"] == -23.3
    assert v2["ecart_marge"] == 50_000 and v2["delai"]["tenable"] is True
    assert bc.comparer({"revenu": 0, "couts": {"a": 1}}, [{}])["valide"] is False
    assert bc.comparer({"revenu": 100, "couts": {"a": 1}}, [])["valide"] is False


def test_risk_thresholds():
    assert [bc.risque_dependance_fournisseur(x) for x in (0.1, 0.5, 0.7, 0.9, None)] == [bc.FAIBLE, bc.MODERE, bc.ELEVE, bc.EXTREME, bc.INCONNU]
    assert bc.risque_delai(-1, 100) == bc.EXTREME and bc.risque_delai(1, 100) == bc.ELEVE and bc.risque_delai(10, 100) == bc.MODERE and bc.risque_delai(20, 100) == bc.FAIBLE
    assert [bc.risque_tresorerie(d, 100) for d in (40, 60, 90, 150)] == [bc.FAIBLE, bc.MODERE, bc.ELEVE, bc.EXTREME]
    assert bc.risque_tresorerie(10, 0) == bc.EXTREME and bc.risque_tresorerie(0, 0) == bc.FAIBLE and bc.risque_tresorerie(None, 5) == bc.INCONNU
    assert bc.risque_concentration_client(0.1) == bc.FAIBLE and bc.risque_concentration_client(0.6) == bc.EXTREME


def test_global_risk_is_the_worst_measured_factor_and_unknown_never_masks():
    g = bc.risque_global(dependance_fournisseur=0.1, marge_jours=-2, duree_totale_jours=10)
    assert g["niveau_global"] == bc.EXTREME and g["facteurs"]["tresorerie"] == bc.INCONNU
    assert bc.risque_global(dependance_fournisseur=0.1)["niveau_global"] == bc.FAIBLE        # facteurs inconnus : n'aggravent rien
    assert bc.risque_global()["niveau_global"] == bc.INCONNU


def test_concentration_clients_by_hand():
    r = bc.concentration_clients({"A": 600, "B": 300, "C": 100, "D": 0, "E": -5})
    assert r["total"] == 1000 and r["plus_gros"] == {"client": "A", "part_pct": 60.0, "niveau": bc.EXTREME}
    assert [c["part_pct"] for c in r["clients"]] == [60.0, 30.0, 10.0]
    assert bc.concentration_clients({})["valide"] is False


def test_agent_tool_is_declared_and_uses_real_invoices_for_client_concentration():
    from app import agent, agents
    from app.database import SessionLocal
    from app.main import app
    from app.models import Customer, Invoice
    assert "business_calc" in {t["name"] for t in agent.TOOLS} and "business_calc" in agents.SAFE_TOOLS
    assert "business_calc" not in agent.UNTRUSTED_SOURCES                                      # calcul pur : pas de contenu de tiers
    with TestClient(app):
        db = SessionLocal()
        try:
            tag = uuid.uuid4().hex[:6]
            big = Customer(code=f"BC{tag}A", name=f"Gros client {tag}")
            small = Customer(code=f"BC{tag}B", name=f"Petit client {tag}")
            db.add_all([big, small]); db.flush()
            db.add_all([Invoice(number=f"F-BC{tag}1", customer_id=big.id, status="approved", total=9_000_000, kind="invoice"),
                        Invoice(number=f"F-BC{tag}2", customer_id=small.id, status="paid", total=1_000_000, kind="invoice"),
                        Invoice(number=f"F-BC{tag}3", customer_id=small.id, status="draft", total=99_000_000, kind="invoice"),      # brouillon : ignoré
                        Invoice(number=f"F-BC{tag}4", customer_id=small.id, status="approved", total=5_000_000, kind="credit")])    # avoir : ignoré
            db.commit()
            s = agent.AgentSession(db, None)
            out = s._t_business_calc("concentration_clients")
            names = {c["client"]: c["montant"] for c in out["clients"]}
            assert names[f"Gros client {tag}"] >= 9_000_000 and names[f"Petit client {tag}"] >= 1_000_000
            assert 99_000_000 not in names.values() and "brouillons" in out["note"]
            assert s._t_business_calc("echeancier", total=300, etapes=[{"libelle": "A", "pourcentage": 50}, {"libelle": "B", "pourcentage": 50}])["valide"]
            assert s._t_business_calc("risque", facteurs={"dependance_fournisseur": 0.9, "intrus": 1})["niveau_global"] == bc.EXTREME     # clé inconnue ignorée
            assert s._t_business_calc("inconnue")["valide"] is False
        finally:
            db.close()
