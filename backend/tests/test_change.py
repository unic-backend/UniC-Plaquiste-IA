"""Taux de change (brique trouvée dans le catalogue public-apis) : FCFA ↔ euro à la parité fixe sans réseau, autres monnaies au taux
de référence BCE (Frankfurter), jamais devinés. Le service est simulé ici (pas de réseau dans les tests)."""
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import change
from app.agent import TOOLS, AgentSession
from app.agents import SAFE_TOOLS
from app.database import SessionLocal
from app.main import app


@pytest.fixture(autouse=True)
def _vide_le_cache():
    change._cache.clear()
    yield
    change._cache.clear()


def _fake(calls: list, rates: dict):
    def get(params):
        calls.append(dict(params))
        return {"amount": 1.0, "base": "EUR", "date": "2026-11-06", "rates": {k: v for k, v in rates.items() if k == params["symbols"]}}
    return get


def test_fcfa_euro_parite_fixe_sans_reseau(monkeypatch):
    calls = []
    monkeypatch.setattr(change, "_get", _fake(calls, {}))
    out = change.convertir(1000, "euro", "fcfa")
    assert out["resultat"] == 655957 and out["de"] == "EUR" and out["vers"] == "XOF" and "BCEAO" in out["source"]
    assert change.convertir("655 957", "FCFA", "EUR")["resultat"] == 1000.0
    assert "note" not in out and calls == []          # parité fixe : aucun appel réseau, pas de marge à signaler


def test_dollar_et_yuan_au_taux_bce_avec_date_et_note(monkeypatch):
    calls = []
    monkeypatch.setattr(change, "_get", _fake(calls, {"USD": 1.1165, "CNY": 7.95}))
    out = change.convertir(1500, "dollars")            # vers FCFA par défaut
    assert out["resultat"] == round(1500 * 655.957 / 1.1165) and out["date_du_taux"] == "2026-11-06"
    assert "Banque centrale européenne" in out["source"] and "marge" in out["note"]
    yuan = change.convertir(980, "yuan", "USD")        # deux monnaies hors euro : passage par l'euro
    assert yuan["resultat"] == round(980 * 1.1165 / 7.95, 2)
    change.convertir(10, "USD")
    assert [c["symbols"] for c in calls] == ["USD", "CNY"]   # le dollar sort du cache la 2e fois


def test_refus_clairs_jamais_de_taux_invente(monkeypatch):
    monkeypatch.setattr(change, "_get", _fake([], {}))
    assert "non publiée" in change.convertir(10, "MAD")["error"]
    assert "inconnue" in change.convertir(10, "bitcoin")["error"]
    assert "illisible" in change.convertir("dix", "USD")["error"]
    assert "positif" in change.convertir(-5, "USD")["error"]

    def down(params):
        raise httpx.ConnectError("coupure")
    monkeypatch.setattr(change, "_get", down)
    assert "indisponible" in change.convertir(10, "USD")["error"]
    assert change.convertir(10, "EUR")["resultat"] == 6560   # la parité fixe marche même sans réseau


def test_outil_de_l_ia_lecture_seule(monkeypatch):
    monkeypatch.setattr(change, "_get", _fake([], {"USD": 1.1165}))
    assert "exchange_rate" in {t["name"] for t in TOOLS} and "exchange_rate" in SAFE_TOOLS
    with TestClient(app), SessionLocal() as db:
        out = AgentSession(db, None, {})("exchange_rate", {"montant": 100, "de": "USD"})
    assert out["vers"] == "XOF" and out["resultat"] == round(100 * 655.957 / 1.1165)


def test_script_pour_claude_code():
    script = Path(__file__).resolve().parents[2] / "scripts" / "unic_change.py"
    r = subprocess.run([sys.executable, str(script), "1000", "EUR"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "655 957 XOF" in r.stdout
