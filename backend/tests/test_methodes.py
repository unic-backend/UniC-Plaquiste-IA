"""Méthodes métier (idée de claude-skills / pm-skills, écrites pour UniC) : liste courte dans l'outil, méthode complète à la demande,
règle commune « chiffres de l'entreprise : jamais inventés »."""
from fastapi.testclient import TestClient

from app import methodes
from app.agent import TOOLS, AgentSession
from app.database import SessionLocal
from app.main import app


def test_chaque_methode_est_complete_et_rappelle_la_regle_des_chiffres():
    assert len(methodes.METHODES) == 8
    for key, m in methodes.METHODES.items():
        assert m["titre"] and m["quand"] and m["rendu"] and len(m["etapes"]) >= 4, key
        out = methodes.get(key)
        assert out["etapes"] == m["etapes"] and "s'invente pas" in out["regles"]
    assert "get_prices" in " ".join(methodes.METHODES["prix"]["etapes"])                 # le prix part des prix du patron
    assert "jamais de prix inventé" in " ".join(methodes.METHODES["appel_offres"]["etapes"])


def test_nom_tolerant_et_methode_inconnue():
    assert methodes.get(" Plan-Marketing ")["methode"] == "plan_marketing"
    bad = methodes.get("astrologie")
    assert "inconnue" in bad["error"] and "plan_marketing" in bad["error"]


def test_outil_method_court_dans_la_description_et_charge_a_la_demande():
    tool = next(t for t in TOOLS if t["name"] == "method")
    assert all(k in tool["description"] for k in methodes.METHODES)
    assert len(tool["description"]) < 1500                                              # seule la liste courte coûte des tokens
    with TestClient(app), SessionLocal() as db:
        out = AgentSession(db, None, {})("method", {"nom": "decision"})
    assert out["titre"] == "Aide à la décision" and len(out["etapes"]) == 5
