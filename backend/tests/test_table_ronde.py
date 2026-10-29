"""Table ronde qui débat : experts choisis selon le problème (un prêt bancaire n'est plus jugé par un métreur), deux tours (chacun lit
les autres, conteste, corrige), puis un arbitre au modèle le plus fort rend la MEILLEURE SOLUTION. Elle se réunit quand le patron
la demande (« table ronde », « à plusieurs », « meilleure solution ») ou en réflexion profonde sur un vrai problème."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import orchestrator, roundtable
from app.config import settings
from app.main import app


@pytest.mark.parametrize("topic, context, panel", [
    ("Devis plafond", "20 m2 BA13", "placo"),
    ("Mon client ne paie pas, je vais au tribunal ?", "contrat signé, facture 2 000 000", "droit"),
    ("Faut-il prendre un prêt bancaire pour un camion ?", "trésorerie 3 M, marge 20 %", "argent"),
    ("Comment trouver plus de clients sur instagram ?", "", "vente"),
    ("Je dois choisir entre deux associés", "", "general"),
])
def test_experts_choisis_selon_le_probleme(topic, context, panel):
    assert roundtable.panel_for(topic, context)[0] == panel


def test_l_ia_peut_choisir_ses_experts():
    name, roles = roundtable.panel_for("x", "", ["juriste OHADA", "comptable", "banquier"])
    assert name == "sur mesure" and list(roles) == ["juriste OHADA", "comptable", "banquier"]
    assert roundtable.panel_for("Devis plafond", "", ["seul"])[0] == "placo"   # un seul nom : panel du sujet


def test_deux_tours_puis_un_arbitre_au_modele_fort(monkeypatch):
    calls = []

    def fake(system, user, **kw):
        calls.append((system, user, kw))
        if "arbitre" in system:
            return "MEILLEURE SOLUTION : payer comptant."
        role = system.split(",")[0].replace("Tu es ", "")
        return f"position finale de {role}" if "DEUXIÈME TOUR" in system else f"avis de {role}"
    monkeypatch.setattr(roundtable, "_ask", fake)
    out = roundtable.run("Faut-il prendre un prêt bancaire pour un camion ?", "trésorerie 3 M")
    assert out["panel"] == "argent" and out["tours"] == 2 and len(calls) == 7                  # 3 avis, 3 répliques, 1 arbitre
    second = [(s, u) for s, u, _ in calls if "DEUXIÈME TOUR" in s]
    assert len(second) == 3
    for s, u in second:                                                                        # chacun lit les AUTRES, pas lui-même
        me = s.split(",")[0].replace("Tu es ", "")
        assert f"TON AVIS (tour 1) :\navis de {me}" in u and f"[{me}]" not in u and u.count("avis de ") == 3
    arb_sys, arb_user, arb_kw = calls[-1]
    assert "MEILLEURE SOLUTION" in arb_sys and arb_kw["model"] == settings.anthropic_model
    assert "DÉBAT (tour 2)" in arb_user and "position finale de Financier" in arb_user
    assert out["synthese"].startswith("MEILLEURE SOLUTION") and set(out["debat"]) == set(out["experts"])


def test_sans_debat_possible_la_table_rend_quand_meme_un_verdict(monkeypatch):
    monkeypatch.setattr(roundtable, "_ask", lambda s, u, **kw: "" if "DEUXIÈME TOUR" in s else ("verdict" if "arbitre" in s else "avis"))
    out = roundtable.run("Devis plafond", "20 m2")
    assert out["tours"] == 1 and out["debat"] == {} and out["synthese"] == "verdict"
    monkeypatch.setattr(roundtable, "_ask", lambda s, u, **kw: "")
    assert "error" in roundtable.run("Devis plafond", "20 m2")


@pytest.mark.parametrize("text, deep, expect", [
    ("fais une table ronde sur ce devis", False, "PLUSIEURS REGARDS"),
    ("réfléchissez à plusieurs", False, "PLUSIEURS REGARDS"),
    ("quelle est la meilleure solution pour ma trésorerie ?", False, "PLUSIEURS REGARDS"),
    ("consulte les experts", False, "PLUSIEURS REGARDS"),
    ("mon associé veut partir, que faire ?", True, "RÉFLEXION PROFONDE"),
    ("combien de plaques pour 20 m2 ?", False, ""),
])
def test_quand_reunir_la_table(text, deep, expect):
    note = orchestrator.round_table_note(text, deep)
    assert (expect in note) if expect else note == ""


def test_demander_la_table_ronde_passe_en_reflexion_profonde(monkeypatch):
    from app.ai import ClaudeAIProvider
    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(content=[NS(type="text", text="Voici la meilleure solution.", citations=None)], stop_reason="end_turn", model="m",
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                           server_tool_use=NS(web_search_requests=0)))
    monkeypatch.setattr(settings, "local_ai_url", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "secret-key")
    monkeypatch.setattr(ClaudeAIProvider, "_client", lambda self: NS(beta=NS(messages=NS(create=create)), messages=NS(create=create)))
    with TestClient(app) as c:
        c.post("/api/chat", json={"message": "table ronde : je prends un prêt pour acheter un camion ou je loue ?"})
    first = calls[0]
    assert "PLUSIEURS REGARDS" in str(first["system"]) and first["model"] == settings.anthropic_model   # modèle le plus fort
    assert any(t.get("name") == "round_table" for t in first.get("tools") or [])
