"""Le patron écrit vite et relance court. « continue », « on y vas », « travailles », « vazy » = la SUITE du travail en cours (avant :
« continue » partait seul, sans contexte, et la mémoire cherchait le mot « continue »). « fai le devi d'une cloisson de 4 mettre
pr moussa ba » = un devis de cloison de 4 m pour Moussa Ba (avant : rien de reconnu sans IA cloud). Les mots justes ne changent pas."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import calc, orchestrator
from app.database import SessionLocal
from app.main import app
from app.models import Quotation, QuotationItem


@pytest.mark.parametrize("text", [
    "continue", "Continue !", "continu", "contunue", "continuer", "travaille", "travailles", "travaille stp", "on y va", "on y vas",
    "On y va !", "vas-y", "vas y", "vazy", "ok vas y", "go", "la suite", "étape suivante", "etape suivante", "termine", "finis",
    "encore", "reprends", "fais-le", "fait le", "allez", "allez-y", "allons-y", "oui continue", "waaw continue", "poursuis",
    "continue le travail", "fonce", "c'est parti",
])
def test_relance_reconnue_meme_mal_ecrite(text):
    assert orchestrator.RELANCE_RE.match(text)


@pytest.mark.parametrize("text", [
    "continue le devis de Moussa Ba pour 3 cloisons", "oui", "ok", "merci", "la suite de fibonacci", "go to google",
    "encore une question : combien de plaques ?", "fais le devis pour moussa ba",
])
def test_une_vraie_demande_n_est_pas_une_relance(text):
    assert not orchestrator.RELANCE_RE.match(text)


def test_la_relance_rappelle_la_tache_en_cours():
    history = [NS(role="user", content="continue"),                                    # du plus récent au plus ancien
               NS(role="assistant", content="Calcul fait : 9 plaques. Je prépare le devis pour Awa Fall ?"),
               NS(role="user", content="cloison 4 x 2,5 deux faces, devis pour Awa Fall")]
    note = orchestrator.relance_note("on y vas", history)
    assert "RELANCE DU PATRON" in note and "Ne redemande pas" in note
    assert "Sa demande en cours : « cloison 4 x 2,5 deux faces, devis pour Awa Fall »" in note   # pas « continue »
    assert "Je prépare le devis pour Awa Fall ?" in note
    assert "RIEN N'EST EN COURS" in orchestrator.relance_note("continue", [])
    assert orchestrator.relance_note("combien de plaques ?", history) == ""


@pytest.mark.parametrize("raw, fixed", [
    ("fai le devi d'une cloisson de 4 mettre pr moussa", "fai le devis d'une cloison de 4 mètres pour moussa"),
    ("faut plafond 5x4", "faux plafond 5x4"),
    ("plafon 5 x 4 et peintur", "plafond 5 x 4 et peinture"),
    ("anduit 30 m2", "enduit 30 m2"),
    ("un facteur est passé", "un facteur est passé"),                         # mots justes : jamais touchés
    ("quelle devise ?", "quelle devise ?"),
    ("il faut mettre la plaque", "il faut mettre la plaque"),                 # « mettre » sans nombre : le verbe
])
def test_fautes_courantes(raw, fixed):
    assert calc.fix_typos(raw) == fixed


@pytest.mark.parametrize("text, intent", [
    ("fai le devi pr moussa ba cloisson 4x2,5", "create_quote"),
    ("fait le devis pour moussa ba", "create_quote"),                         # « fait » pour « fais »
    ("j'ai fait le devis hier", "chat"),                                      # un récit, pas un ordre
    ("cloisson 4 mettre sur 2,5", "calculate"),
    ("faut plafond 5x4", "calculate"),
])
def test_le_routeur_comprend_les_fautes(text, intent):
    assert orchestrator._intent(text, {}) == intent


def test_devis_ecrit_avec_des_fautes_sans_ia_cloud():
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"message": "fai le devi d'une cloisson de 4 mettre sur 2,5 pr moussa ba"}).json()
        qid = r["message"]["meta"]["structured"]["quotation_id"]
        with SessionLocal() as db:
            assert db.get(Quotation, qid).client_label == "Moussa Ba"
            boards = next(i.quantity for i in db.query(QuotationItem).filter(QuotationItem.quotation_id == qid) if "Plaque" in i.description)
            assert boards == 9                                                # 4 × 2,5 × 2 faces × 1,08 / 2,4 → 9


def test_l_ia_recoit_la_tache_en_cours_quand_le_patron_relance(monkeypatch):
    from app.ai import ClaudeAIProvider
    from app.config import settings
    calls = []

    def create(**kw):
        calls.append(kw)
        block = NS(type="text", text="Calcul fait. Je prépare le devis ?", citations=None)
        return NS(content=[block], stop_reason="end_turn", model="m",
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                           server_tool_use=NS(web_search_requests=0)))
    fake = NS(beta=NS(messages=NS(create=create)), messages=NS(create=create))
    monkeypatch.setattr(settings, "local_ai_url", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "secret-key")
    monkeypatch.setattr(ClaudeAIProvider, "_client", lambda self: fake)
    with TestClient(app) as c:
        cid = c.post("/api/chat", json={"message": "calcule une cloison 6 x 2,5 pour Awa Fall"}).json()["conversation_id"]
        c.post("/api/chat", json={"message": "on y vas", "conversation_id": cid})
    system = str(calls[-1]["system"])
    assert "COMPRENDRE LE PATRON" in system and "RELANCES" in system                       # règles 14 et 15
    assert "RELANCE DU PATRON (« on y vas »)" in system
    assert "Sa demande en cours : « calcule une cloison 6 x 2,5 pour Awa Fall »" in system
