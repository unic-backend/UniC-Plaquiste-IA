"""Métier UniC (Sénégal) : faux plafond BA13 et cloison sèche n'ont pas la même ossature ; une surface sans ouvrage n'est jamais
supposée être une cloison (les deux calculs, puis une question) ; l'IA retrouve une info dite autrement (« plafond suspendu »)."""
import pytest
from fastapi.testclient import TestClient

from app import calc, orchestrator, retrieval
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app

CEILING_ONLY = {"UC-TIGES-A-L-UNITE", "UC-PIVOT", "UC-CHEVILLES-A-LETON", "UC-BARRE-DE-FOURRURE-2-90-M", "UC-CORNIERES"}
PARTITION_ONLY = {"MONTANT-M48", "UC-RAILS-48-MM", "UC-VIS-9-MM"}


def _q(res) -> dict:
    return {q.sku: q.quantity for q in res.quantities}


def test_le_plafond_a_son_ossature_et_ses_chevilles_a_frapper():
    q = _q(calc.calculate_ceiling(5, 4))
    assert CEILING_ONLY <= set(q) and not (PARTITION_ONLY & set(q))           # jamais de rails ni de montants au plafond
    assert q["UC-PAQUET-CHEVILLES-A-FRAPPER"] == 1                             # ⌈ (⌈18 / 0,5⌉ + 4) / 100 ⌉ = ⌈40 / 100⌉
    assert any(k.startswith("BA13") for k in q)


def test_la_cloison_a_rails_montants_chevilles_a_frapper_et_vis_9():
    small = calc.calculate_partition(5.4, 2.5, 2)
    q = _q(small)
    assert PARTITION_ONLY <= set(q) and not (CEILING_ONLY & set(q))           # jamais de tiges, pivots ni fourrures en cloison
    assert q["UC-PAQUET-CHEVILLES-A-FRAPPER"] == 1 and q["UC-VIS-9-MM"] == 1  # comme le chantier de référence : 1 paquet par paroi
    assert calc.verify(small)["ok"]
    big = calc.calculate_partition(30, 2.5, 2)
    q = _q(big)
    assert q["UC-PAQUET-CHEVILLES-A-FRAPPER"] == 2                             # ⌈ (⌈60 / 0,5⌉ + 2) / 100 ⌉ = ⌈122 / 100⌉
    assert q["UC-VIS-9-MM"] == 3                                               # (⌈30 / 1,2⌉ × 2 + 1) × 4 = 204 vis
    assert calc.verify(big)["ok"]
    next(x for x in big.quantities if x.sku == "UC-VIS-9-MM").quantity = 1     # chiffre faussé : le contrôle indépendant le voit
    assert not calc.verify(big)["ok"]


@pytest.mark.parametrize("text, kind", [
    ("j'ai une surface de 100 m²", "a_preciser"),
    ("100 m² de BA13", "a_preciser"),
    ("il me faut des plaques pour 80 m2", "a_preciser"),
    ("faux plafond 100 m²", "ceiling"),
    ("plafond suspendu 5 x 4", "ceiling"),
    ("cloison de 100 m²", "partition"),
    ("combien de plaques pour un mur de 12m sur 2.6", "partition"),
    ("peinture 45 m²", "paint"),
    ("surface de 12 x 2,5", "surface"),
])
def test_une_surface_seule_n_est_jamais_une_cloison(text, kind):
    assert calc.detect_calc_kind(text) == kind


def test_sans_ouvrage_l_ia_repond_avec_les_deux_calculs_et_une_question(monkeypatch):
    assert orchestrator._intent("j'ai 100 m² de BA13", {}) == "chat"            # pas le calcul seul : l'IA répond avec les deux
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "a_preciser", "area_m2": 100})
        ceiling = {q["sku"] for q in out["si_plafond"]["quantites"]}
        partition = {q["sku"] for q in out["si_cloison"]["quantites"]}
        assert CEILING_ONLY <= ceiling and not (CEILING_ONLY & partition)
        assert any("Ossature ESTIMÉE" in r for r in out["si_cloison"]["remarques"])   # de quoi travailler, marqué estimé
        assert "plafond ou cloison" in out["note"] and "last_calc" not in s.state      # aucun devis tant que l'ouvrage n'est pas dit
        assert "error" in s("create_quote", {"client_name": "Awa Diop", "checks": "x", "objet": "x"})


def test_cloison_connue_par_sa_surface_estimation_a_part_sans_ossature_inventee():
    res = calc.calculate_partition_from_area(100, 2)
    assert not ({"MONTANT-M48", "UC-RAILS-48-MM"} & set(_q(res)))              # le devis attend la vraie longueur et hauteur
    note = next(n for n in res.notes if "Ossature ESTIMÉE" in n)
    assert "2,5 m de haut" in note.replace("2.5", "2,5") and "40.0 m de long" in note and "montants" in note
    assert calc.verify(res)["ok"]


def test_les_regles_du_patron_sont_dans_les_consignes():
    rules = orchestrator.SYSTEM_RULES
    assert "PLAFOND OU CLOISON" in rules and "kind=\"a_preciser\"" in rules
    assert "LE PATRON PASSE AVANT LES RÈGLES" in rules and "ne refuse jamais" in rules
    assert "chevilles à laiton" in rules and "vis de 9 mm" in rules and "jamais une liste de questions" in rules


@pytest.mark.parametrize("query, expected", [
    ("plafond suspendu chez Fall", "a"),      # « faux plafond »
    ("paroi en placo Diop", "b"),             # « cloison »
    ("les plafonds", "a"),                    # pluriel
    ("tarif des rails", "c"),                 # « prix »
])
def test_la_recherche_comprend_le_sens(query, expected):
    recs = [retrieval.Record("a", "Faux plafond BA13 chez Mme Fall : 40 m², fourrures et tiges."),
            retrieval.Record("b", "Cloison de 12 m au salon chez M. Diop."),
            retrieval.Record("c", "Prix des rails 48 mm : 1 500 FCFA la barre.")]
    assert retrieval.bm25(query, recs)[0][0] == expected


def test_un_mot_dit_compte_plus_qu_un_synonyme():
    w = retrieval.expand_query("plafond suspendu")
    assert w["plafond"] == 1 and w["suspendu"] == 1 and w["placo"] == retrieval.SYNONYM_WEIGHT
