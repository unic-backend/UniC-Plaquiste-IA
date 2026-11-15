"""Formation UniC : cours sans IA, corrigé par le moteur, suivi par élève."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import formation


@pytest.fixture
def c():
    with TestClient(app) as client:
        yield client


def test_cours_exemple_du_moteur_et_sans_prix(c):
    r = c.get("/api/formation").json()
    plafond = next(m for m in r["modules"] if m["id"] == "plafond")
    got = {x["question"]: x["quantite"] for x in plafond["exemple"]["resultat"]}
    # Cas de référence du tuteur (EXEMPLES.md) : salon 5 × 4 sur dalle.
    assert got == {"Combien de plaques ?": 12, "Combien de tiges ?": 54, "Combien de barres de fourrure ?": 20, "Combien de cornières ?": 10}
    assert "prix" not in str(r).lower().replace("le prix de l'électricité", "")
    assert all("ok" not in q and "pourquoi" not in q for q in r["quiz"])   # la réponse reste au serveur


def test_exercice_deterministe_et_corrige(c):
    a = c.get("/api/formation/exercice", params={"type": "plafond", "seed": 7}).json()
    assert a == c.get("/api/formation/exercice", params={"type": "plafond", "seed": 7}).json()
    assert all("attendu" not in q for q in a["questions"])
    faux = c.post("/api/formation/exercice/corriger", json={"eleve": "Moussa", "type": "plafond", "seed": 7, "reponses": {}}).json()
    assert faux["bon"] == 0 and faux["verdict"] == "refaire"
    justes = {l["sku"]: l["attendu"] for l in faux["lignes"]}
    bon = c.post("/api/formation/exercice/corriger",
                 json={"eleve": "Moussa", "type": "plafond", "seed": 7, "reponses": justes, "examen": True}).json()
    assert bon["bon"] == bon["total"] > 0 and bon["verdict"] == "tâche complète"
    s = c.post("/api/formation/suivi", json={"eleve": "Moussa"}).json()
    assert s["exercices"] >= 2 and s["dernier_examen"]["bon"] == bon["total"]
    assert c.get("/api/formation/exercice", params={"type": "xx", "seed": 1}).status_code == 400


def test_cloison_sans_marge_et_quiz_revision(c):
    for seed in range(5):
        ex = c.post("/api/formation/exercice/corriger", json={"eleve": "Awa", "type": "cloison", "seed": seed, "reponses": {}}).json()
        assert all("marge" not in l["calcul"] for l in ex["lignes"])
    r = c.post("/api/formation/quiz", json={"eleve": "Awa", "question": "q7", "choix": 2, "certitude": "deviné"}).json()
    assert r["ok"] and r["revoir"]   # juste mais deviné : à revoir dans 2 jours
    assert c.post("/api/formation/quiz", json={"eleve": "Awa", "question": "q7", "choix": 2, "certitude": "bof"}).status_code == 400
    p = c.post("/api/formation/lecon", json={"eleve": "Awa", "lecon": "plafond"}).json()
    assert p["lecons"] == ["plafond"] and "Awa" in c.get("/api/formation").json()["eleves"]


def test_quiz_reponses_valides():
    for q in formation.QUIZ:
        assert 0 <= q["ok"] < len(q["choix"])
