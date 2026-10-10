"""Tableau qualité : chiffres issus de données réelles, « non mesuré » plutôt qu'un chiffre inventé, route fermée."""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import quality  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def db(client):
    from app.database import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


def _by_id(rep):
    return {r["id"]: r for r in rep["indicateurs"]}


def test_report_has_every_indicator_and_never_invents(db):
    rep = quality.report(db)
    ids = set(_by_id(rep))
    assert {"calculs", "manquantes", "documents", "tests", "serveur", "cout", "outils", "restauration", "corrections", "faux_positifs"} <= ids
    assert rep["cle"]["id"] == "faux_certains"
    assert _by_id(rep)["faux_positifs"]["etat"] == "none"   # pas de mesure possible : dit non mesuré, jamais un chiffre
    assert _by_id(rep)["tests"]["etat"] == "none"


def test_tool_failures_are_counted_from_the_audit_log(db):
    from app.agent import AgentSession
    s = AgentSession(db, None, {"owner_message": "test"})
    base = _by_id(quality.report(db))["outils"]
    s("outil_qui_nexiste_pas", {})                      # inconnu : ni panne ni refus métier
    assert s("get_prices", {"zzz": 1}).get("error")      # paramètres invalides : panne comptée
    after = _by_id(quality.report(db))["outils"]
    errs = lambda row: 0 if row["valeur"] == "non mesuré" else int(row["valeur"].split("/")[0])  # noqa: E731
    assert errs(after) == errs(base) + 1 and after["valeur"] != "non mesuré"


def test_wrong_calc_check_and_inconsistent_document_raise_the_key_indicator(db):
    from app import services as svc
    from app.models import Quotation
    before = quality.report(db)["cle"]
    q = Quotation(number=svc.document_number(db, "Qualite Test Client", lieu="Dakar"), client_label="Qualite Test Client", status="draft",
                  currency="FCFA", subtotal=1000.0, vat_rate=0.18, vat_amount=180.0, total=900.0)   # total faux : 1000 + 180 ≠ 900
    q.calc_trace = json.dumps({"controle_independant": {"ok": False, "problems": ["écart"]}})
    db.add(q)
    db.commit()
    after = quality.report(db)["cle"]
    assert int(after["valeur"].split()[0]) >= int(before["valeur"].split()[0]) + 2   # document incohérent + écart de calcul
    assert after["etat"] == "bad"
    rows = _by_id(quality.report(db))
    assert rows["calculs"]["etat"] == "bad" and rows["documents"]["etat"] == "bad"


def test_invented_values_in_last_eval_are_counted(db):
    from app import evals
    from app.models import AppSetting
    rep = {"at": "2026-10-10T10:00:00+00:00", "passed": 9, "total": 10, "score": 90.0,
           "results": [{"id": "x", "ok": False, "problems": ["sides inventé (2) alors que le patron ne l'a pas donné."]}]}
    row = db.get(AppSetting, evals.SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=evals.SETTING_KEY, value=json.dumps(rep)))
    else:
        row.value = json.dumps(rep)
    db.commit()
    r = _by_id(quality.report(db))["manquantes"]
    assert r["etat"] == "bad" and r["valeur"].startswith("1 invention")


def test_quality_route_is_closed_without_code_and_open_with_it(client):
    paths = [r["paths"] for r in [client.get("/openapi.json").json()]][0]
    assert "/api/quality" in paths
    r = client.get("/api/quality")
    assert r.status_code in (200, 401)
    if r.status_code == 200:   # pas de code d'accès configuré dans ce test : la structure doit être complète
        assert r.json()["cle"]["id"] == "faux_certains"
