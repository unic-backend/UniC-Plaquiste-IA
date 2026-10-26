"""Vérité des chiffres : après des outils, chaque montant et pourcentage de la réponse doit venir de leurs résultats, du contexte,
ou d'un calcul juste ; sinon la relecture (qui voit les résultats) corrige, ou le chiffre est signalé. Les tâches complexes ont
plus d'étapes d'outils."""
import pytest
from fastapi.testclient import TestClient

from app import ai, relecture
from app.agent import AgentSession
from app.ai import PROVIDERS, AIResult
from app.config import settings
from app.database import SessionLocal
from app.main import app

TOOLS = ('[business_report] {"chiffres": {"encaisse": {"valeur": 500000.0, "avant": 400000.0}, "signe": {"valeur": 1000000.0}}, '
         '"clients": {"top": [{"client": "Awa", "encaisse": 300000, "part_pct": 60.0}, {"client": "Moussa", "encaisse": 200000}]}, '
         '"plaques": 77, "prix": 4500}')


@pytest.mark.parametrize("reply, unsourced", [
    ("Tu as encaissé **500 000 FCFA** ce mois, contre 400 000 FCFA avant (+25 %).", []),      # évolution = écart / avant
    ("Awa pèse 60 % des encaissements, Moussa 40 %.", []),                                       # part de deux montants
    ("Signé : 1 M FCFA ; 77 plaques × 4 500 = 346 500 FCFA.", []),                               # arrondi lisible ; calcul écrit juste
    ("À eux deux : 700 000 FCFA, soit 100 000 FCFA d'écart avec Awa seule.", []),                 # somme et écart
    ("Appelle le 77 123 45 67 avant le 24/10/2026.", []),                                        # téléphone et date : pas des montants
    ("Tu as encaissé 750 000 FCFA ce mois.", ["750 000 FCFA"]),                                  # inventé
    ("Ta marge nette est de 37 %.", ["37 %"]),
])
def test_chiffres_sans_source(reply, unsourced):
    assert relecture.unsourced_figures(reply, TOOLS) == unsourced


@pytest.fixture
def fake(monkeypatch):
    state = {"available": True, "review": "CORRIGÉ\nEncaissé corrigé d'après le bilan.\n---\nTu as encaissé 500 000 FCFA ce mois.",
             "asked": []}

    def complete(self, messages, **kw):
        state["asked"].append(messages[-1]["content"])
        return AIResult(state["review"], "claude", "claude-opus-5-5", True, "", raw={"usage": []})
    monkeypatch.setattr(type(PROVIDERS["claude"]), "health", lambda self: {"available": state["available"]})
    monkeypatch.setattr(type(PROVIDERS["claude"]), "complete", complete)
    with TestClient(app):
        yield state


def _review(**kw):
    args = {"question": "Combien j'ai encaissé ce mois ?", "reply": "Tu as encaissé 750 000 FCFA ce mois.", "context": "",
            "deep": False, "voice": False, "succeeded": ["business_report"], "tool_results": TOOLS}
    with SessionLocal() as db:
        return relecture.review(db, **{**args, **kw})


def test_un_chiffre_invente_apres_un_outil_est_corrige_avec_les_vrais_resultats(fake):
    out = _review()
    assert out.status == "corrected" and "500 000 FCFA" in out.text and "750 000" not in out.text
    sent = fake["asked"][0]
    assert "RÉSULTATS DES OUTILS DE CE TOUR" in sent and '"valeur": 500000.0' in sent and "750 000 FCFA" in sent.split("INTROUVABLES")[1]


def test_sans_relecture_possible_le_chiffre_est_signale(fake):
    fake["available"] = False
    out = _review()
    assert out.status == "warned" and "Chiffres non retrouvés dans les données : 750 000 FCFA" in out.text


def test_chiffres_justes_ou_venus_d_internet_pas_de_relecture(fake):
    assert _review(reply="Tu as encaissé 500 000 FCFA, contre 400 000 FCFA avant.").status == "skipped"
    assert _review(web_used=True).status == "skipped"            # chiffres d'Internet : pas dans les résultats d'outils
    assert fake["asked"] == []


def test_la_session_garde_les_resultats_des_outils(fake):
    with SessionLocal() as db:
        s = AgentSession(db, None, {})
        s("cash_forecast", {})
        s("table_info", {"file_id": "inconnu"})                   # en erreur : pas gardé
    assert [n for n, _ in s.results] == ["cash_forecast"] and '"semaines"' in s.results[0][1]


def test_une_tache_complexe_a_plus_d_etapes_d_outils(monkeypatch):
    claude, seen = PROVIDERS["claude"], []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(type(claude), "_client", lambda self: object())

    class R:
        stop_reason, content, usage = "end_turn", [], None
    monkeypatch.setattr(type(claude), "_run", lambda self, client, params, handler, used: seen.append(ai.ROUNDS.get()) or R())
    msgs = [{"role": "user", "content": "x"}]
    claude.complete(msgs)
    claude.complete(msgs, max_rounds=14)
    claude.complete(msgs, max_rounds=99)
    assert seen == [0, 14, 16] and ai.ROUNDS.get() == 0              # 0 = valeur du fournisseur (8) ; borné à 16 ; remis après
