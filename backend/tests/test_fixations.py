"""Fixations réglables : contenu des paquets de chevilles à frapper et de vis de 9 mm, espacement, vis par montant. Écart des
chevilles (30 cm) et vis par montant (4) : validés par le patron (« confirmé ») ; tailles de paquet vides = supposées ; données
par le patron (Réglages ou chat) = « confirmé », et le contrôle indépendant recalcule avec les mêmes valeurs. Le plafond est
chiffré jusqu'aux finitions (vis, bande, enduit, validées par le patron)."""
import pytest
from fastapi.testclient import TestClient

from app import calc, memory
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import CompanySettings

KEYS = ("anchor_spacing_m", "anchors_per_pack", "screws9_per_stud", "screws9_per_pack")


def _line(res, sku):
    return next(q for q in res.quantities if q.sku == sku)


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client
        with SessionLocal() as db:   # réglages remis à vide : les autres tests gardent les suppositions par défaut
            row = db.query(CompanySettings).first()
            if row is not None:
                for k in KEYS:
                    setattr(row, k, None)
                db.commit()


def test_valeurs_du_patron_dans_le_calcul_et_le_controle():
    res = calc.calculate_partition(30, 2.5, 2, fixing_values={"anchors_per_pack": 50, "screws9_per_pack": 1000})
    anchors, screws = _line(res, "UC-PAQUET-CHEVILLES-A-FRAPPER"), _line(res, "UC-VIS-9-MM")
    assert anchors.quantity == 5 and anchors.name == "Chevilles à frapper (paquet de 50)"     # ⌈(⌈60 / 0,30⌉ + 2) / 50⌉ = ⌈202 / 50⌉
    assert screws.quantity == 1 and screws.name == "Vis 9 mm (paquet de 1000)"                # ⌈204 / 1000⌉
    assert "1 tous les 30 cm de rail" in anchors.formula
    assert anchors.status == screws.status == calc.STATUS_CONFIRMED   # écart et vis par montant validés + paquet donné
    paquets_supposes = calc.calculate_partition(30, 2.5, 2)
    assert _line(paquets_supposes, "UC-PAQUET-CHEVILLES-A-FRAPPER").status == calc.STATUS_ASSUMED   # paquet de 100 supposé
    assert calc.verify(res)["ok"]
    full = calc.calculate_partition(30, 2.5, 2, fixing_values={k: v for k, v in zip(KEYS, (0.6, 50, 2, 1000))})
    assert _line(full, "UC-PAQUET-CHEVILLES-A-FRAPPER").status == calc.STATUS_CONFIRMED
    assert _line(full, "UC-PAQUET-CHEVILLES-A-FRAPPER").quantity == 3                        # ⌈(⌈60 / 0,6⌉ + 2) / 50⌉ = ⌈102 / 50⌉
    assert calc.verify(full)["ok"] and any("données par le patron" in a for a in full.assumptions)
    defaults = calc.calculate_partition(30, 2.5, 2)
    assert _line(defaults, "UC-VIS-9-MM").quantity == 3 and any("Réglages" in a for a in defaults.assumptions)


def test_le_plafond_est_chiffre_jusqu_aux_finitions():
    res = calc.calculate_ceiling(5, 4, fixing_values={"anchor_spacing_m": 0.4, "anchors_per_pack": 20})
    q = {x.sku: x.quantity for x in res.quantities}
    assert q["VIS-PLAQUE"] == 300 and q["BANDE-JOINT"] == 28 and q["ENDUIT-JOINT"] == 14       # 20 m² × 15 ; × 1,4 ; × 0,35 × 2
    assert q["UC-PAQUET-CHEVILLES-A-FRAPPER"] == 3                                            # ⌈(⌈18 / 0,4⌉ + 4) / 20⌉ = ⌈49 / 20⌉
    assert not any("non chiffrés" in m for m in res.missing) and calc.verify(res)["ok"]


def test_reglages_et_chat(c):
    r = c.put("/api/settings", json={"anchors_per_pack": 200, "screws9_per_pack": 500})
    assert r.status_code == 200
    with SessionLocal() as db:
        s = AgentSession(db, None, {"owner_message": "calcule une cloison de 30 m sur 2,50 m"})
        out = s("calculate_materials", {"kind": "partition", "length_m": 30, "height_m": 2.5, "sides": 2})
        lines = {q["sku"]: q for q in out["quantites"]}
        assert lines["UC-PAQUET-CHEVILLES-A-FRAPPER"]["quantity"] == 2 and "paquet de 200" in lines["UC-PAQUET-CHEVILLES-A-FRAPPER"]["name"]   # ⌈202 / 200⌉
        assert lines["UC-VIS-9-MM"]["quantity"] == 1                                         # ⌈204 / 500⌉
        s = AgentSession(db, None, {"owner_message": "mes paquets de vis 9 font 1000"})
        out = s("set_fixings", {"screws9_per_pack": 1000})
        assert out["enregistre"] == {"screws9_per_pack": 1000} and out["valeurs"]["screws9_per_pack"] == 1000
        assert out["valeurs"]["anchors_per_pack"] == 200                                       # l'autre réglage est gardé
        assert "error" in s("set_fixings", {}) and "hors limites" in s("set_fixings", {"screws9_per_stud": 99})["error"]
    assert c.put("/api/settings", json={"anchors_per_pack": 0}).status_code == 422
    assert c.put("/api/settings", json={"anchors_per_pack": None, "screws9_per_pack": None}).status_code == 200   # retour aux suppositions
    assert c.get("/api/settings").json()["anchors_per_pack"] is None


def test_chevilles_a_30_cm_reglage_fiche_et_memoire_une_fois():
    from app.models import AppSetting, KnowledgeArticle, Memory
    from app.seed import _OLD_FIXINGS_TEXT, apply_owner_fixings_v12
    with TestClient(app), SessionLocal() as db:
        co = db.query(CompanySettings).first()
        co.anchor_spacing_m = 0.5                                     # l'ancienne valeur supposée, enregistrée dans Réglages
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == "methode-ossature").first()
        art.body = "Montants : …\n" + _OLD_FIXINGS_TEXT
        row = db.get(AppSetting, "seed_owner_fixings_v12")
        if row:
            db.delete(row)
        db.commit()
        try:
            assert apply_owner_fixings_v12(db) == 2 and apply_owner_fixings_v12(db) == 0   # une seule fois
            db.refresh(co)
            db.refresh(art)
            assert co.anchor_spacing_m == 0.30
            assert "une tous les 30 cm" in art.body and "(hypothèse" not in art.body and "validé par le patron" in art.body
            for m in db.query(Memory).filter(Memory.text.like("Chevilles à frapper : une tous les 30 cm%")):
                db.delete(m)
            flag = db.get(AppSetting, "seed_owner_rules_v18")
            if flag:
                db.delete(flag)
            db.commit()
            assert memory.seed_owner_rules(db) == 1                     # règle V18 posée une fois
            assert db.query(Memory).filter(Memory.state == "active", Memory.text.like("Chevilles à frapper : une tous les 30 cm%")).count() == 1
        finally:
            co.anchor_spacing_m = None
            db.commit()
