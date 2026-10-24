"""Relecture avant envoi : les calculs écrits sont refaits sans IA ; une réponse à enjeu est relue et corrigée par Claude
avant d'arriver au patron ; une correction douteuse est jetée ; le patron peut couper la relecture."""
import pytest
from fastapi.testclient import TestClient

from app import relecture
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, CompanySettings


@pytest.mark.parametrize("text, wrong", [
    ("Surface : 12 × 2,5 = 30 m².", 0),
    ("Surface : 12 m × 2,5 m = 31 m².", 1),
    ("Total : 1 250 000 + 750 000 = 2 000 000 FCFA.", 0),
    ("Total : 1 250 000 + 750 000 = 1 900 000 FCFA.", 1),
    ("Acompte : 2 000 000 × 30 % = 600 000 FCFA.", 0),
    ("Acompte : 2 000 000 × 30 % = 650 000 FCFA.", 1),
    ("1 + 2 × 3 = 7", 0),                                   # × avant +
    ("1 + 2 × 3 = 9", 1),
    ("100 / 3 = 33,33", 0),                                 # arrondi affiché
    ("12 × 2,5 = 30 m² × 2 faces = 60 m²", 0),              # calcul enchaîné
    ("12 × 2,5 = 30 m² × 2 faces = 70 m²", 1),
    ("4 500 FCFA x 77 plaques = 346 500 FCFA", 0),
    ("Le 24/10/2026 à 10 h, 3 plaques.", 0),                # une date n'est pas une division
    ("Pose de 8 h - 12 h = 4 h.", 0),                       # une plage, pas une soustraction
    ("≈ 3 × 3 ≈ 10", 0),                                    # « environ » : pas contrôlé
])
def test_les_calculs_ecrits_sont_refaits(text, wrong):
    found = relecture.arith_errors(text)
    assert len(found) == wrong
    if wrong:
        assert "le bon résultat" in found[0]


ANSWER = ("Pour un contrat de 2 000 000 FCFA, l'acompte usuel de 30 % donne : 2 000 000 × 30 % = 650 000 FCFA. "
          "Le solde est payé à la réception des travaux. Fais signer l'avenant avant tout changement de prix.")
FIXED = ("Pour un contrat de 2 000 000 FCFA, l'acompte usuel de 30 % donne : 2 000 000 × 30 % = 600 000 FCFA. "
         "Le solde est payé à la réception des travaux. Fais signer l'avenant avant tout changement de prix.")


@pytest.fixture
def fake(monkeypatch):
    """Faux Claude posé sur la CLASSE (remis exactement en place après le test) : rédaction, relecture, le reste."""
    state = {"review": "CORRIGÉ\nAcompte recalculé : 30 % de 2 000 000 font 600 000 FCFA.\n---\n" + FIXED,
             "answer": ANSWER, "available": True, "calls": []}

    def complete(self, messages, **kw):
        system = " ".join(m["content"] for m in messages if m["role"] == "system")
        kind = "review" if "RELECTEUR" in system else "answer" if "Tu es UniC" in system else "other"
        state["calls"].append(kind)
        text = state[kind] if kind != "other" else "[]"
        return AIResult(text, "claude", "claude-opus-5-5", True, "", raw={"usage": []})
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "unic_access_code", "")
    monkeypatch.setattr(type(PROVIDERS["claude"]), "health", lambda self: {"available": state["available"]})
    monkeypatch.setattr(type(PROVIDERS["claude"]), "complete", complete)
    with TestClient(app):
        yield state


def _review(**kw):
    args = {"question": "Quel acompte pour ce contrat ?", "reply": ANSWER, "context": "", "deep": True, "voice": False, "succeeded": []}
    with SessionLocal() as db:
        return relecture.review(db, **{**args, **kw})


def test_une_reponse_a_enjeu_fausse_est_corrigee_avant_envoi(fake):
    out = _review()
    assert out.status == "corrected" and "600 000 FCFA" in out.text and "650 000" not in out.text
    assert "Relue avant envoi : Acompte recalculé" in out.text and fake["calls"] == ["review"]


def test_rien_a_corriger_la_reponse_part_telle_quelle(fake):
    fake["review"] = "OK"
    out = _review(reply=FIXED)
    assert out.status == "ok" and out.text == FIXED


def test_pas_de_relecture_sans_enjeu_en_vocal_ou_si_le_patron_la_coupe(fake):
    assert _review(reply=FIXED, deep=False).status == "skipped"                  # banalité : pas d'appel en plus
    assert _review(voice=True).status == "skipped"                               # vocal : dit au fil de l'eau
    assert _review(reply=FIXED, succeeded=["get_prices"]).status == "skipped"   # chiffres venus d'outils, aucun calcul faux
    with SessionLocal() as db:
        row = db.query(CompanySettings).first() or CompanySettings()
        db.add(row)
        row.ai_self_review = False
        db.commit()
    try:
        assert _review().status == "skipped"
    finally:
        with SessionLocal() as db:
            db.query(CompanySettings).first().ai_self_review = True
            db.commit()
    assert fake["calls"] == []


def test_un_calcul_faux_apres_des_outils_est_relu_ou_signale(fake):
    out = _review(deep=False, succeeded=["get_prices"])                          # calcul faux : relu même sans enjeu
    assert out.status == "corrected" and "600 000" in out.text
    fake["review"] = "CORRIGÉ\nFormulation.\n---\n" + ANSWER                      # « corrige » sans corriger le calcul : jetée
    out = _review()
    assert out.status == "warned" and out.text.startswith(ANSWER) and "⚠️ Calcul à vérifier" in out.text
    fake["available"] = False                                                    # Claude absent : avertissement quand même
    assert _review().status == "warned"


def test_une_correction_qui_invente_une_action_est_jetee(fake):
    fake["review"] = "CORRIGÉ\nAjout.\n---\n" + FIXED + " J'ai créé le devis et je l'ai envoyé au client."
    out = _review()
    assert out.status == "warned" and "J'ai créé le devis" not in out.text


def test_dans_le_chat_le_patron_recoit_la_reponse_corrigee(fake):
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"message": "Quel acompte pour un contrat de 2 000 000 FCFA à 30 % ?"})
    content = r.json()["message"]["content"]
    assert r.status_code == 200 and "600 000 FCFA" in content and "650 000" not in content and "Relue avant envoi" in content
    assert "review" in fake["calls"], (fake["calls"], content)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "ai_review_corrected").count() >= 1
