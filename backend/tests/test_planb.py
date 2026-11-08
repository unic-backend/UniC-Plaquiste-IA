"""Dossier Claude Code → serveur (planb.py, /api/import/plan-a) : une seule base, rejouable, rien d'écrasé, fichier trafiqué refusé."""
import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from app import planb
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Customer, Invoice, Quotation


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def _origin(c) -> dict:
    """Un dossier tel que la session Claude Code l'exporterait : un devis, sa facture, un client — mais d'une AUTRE base
    (autres identifiants, autres numéros) : on prend ce que ce serveur produit puis on le rebaptise."""
    r = c.post("/api/calc/pieces/devis", json={"pieces": [{"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4}],
                                                "client": "Awa Planb Diop", "lieu": "Plateau", "main_oeuvre_m2": 2500})
    assert r.status_code == 200, r.text
    qid = r.json()["id"]
    cid = c.post("/api/customers", json={"name": "Awa Planb Diop"}).json()["id"]   # la fiche client que la session Claude Code aurait créée
    inv = c.post(f"/api/quotes/{qid}/invoice")
    with SessionLocal() as db:
        b = planb.export_bundle(db, None)
    n = uuid.uuid4().hex[:6].upper()
    out = copy.deepcopy({k: v for k, v in b.items()})
    out["customers"] = [x for x in out["customers"] if x["id"] == cid]
    out["quotes"] = [dict(q, customer_id=cid) for q in out["quotes"] if q["id"] == qid]
    out["invoices"] = [i for i in out["invoices"] if i.get("quotation_id") == qid] if inv.status_code == 200 else []
    remap = {}

    def fresh(x):
        remap[x["id"]] = str(uuid.uuid4())
        x["id"] = remap[x["id"]]
    for cu in out["customers"]:
        fresh(cu)
        cu["name"] = f"Client Planb {n}"
        cu["code"] = f"CL-9{n}"
    for q in out["quotes"]:
        old = q["id"]
        fresh(q)
        q["number"] = f"UC-9{n}-Q"
        q["customer_id"] = remap.get(q["customer_id"])
        for i in q["items"]:
            i["id"] = str(uuid.uuid4())
            i["quotation_id"] = q["id"]
        for inv in out["invoices"]:
            if inv["quotation_id"] == old:
                inv["quotation_id"] = q["id"]
    for k, inv in enumerate(out["invoices"]):
        fresh(inv)
        inv["number"] = f"FA-9{n}-{k}"
        inv["customer_id"] = remap.get(inv["customer_id"])
        for i in inv["items"]:
            i["id"] = str(uuid.uuid4())
    return out


def test_import_cree_puis_rejoue_sans_doublon_et_refait_le_pdf(c):
    b = _origin(c)
    assert b["invoices"], "le dossier d'essai doit contenir une facture"
    r = c.post("/api/import/plan-a", json=b)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert len(rep["devis_crees"]) == 1 and rep["conflits"] == [] and len(rep["clients_crees"]) == 1
    num = rep["devis_crees"][0]
    with SessionLocal() as db:
        q = db.query(Quotation).filter(Quotation.number == num).one()
        assert q.items and q.artifact_id and q.total                       # lignes reprises, PDF refait par le serveur
        inv = db.query(Invoice).filter(Invoice.number == rep["factures_creees"][0]).one()
        assert inv.items and inv.artifact_id and inv.quotation_id == q.id   # la facture reste liée à son devis
        assert q.customer_id and db.get(Customer, q.customer_id).name.startswith("Client Planb")
    again = c.post("/api/import/plan-a", json=b).json()                    # rejouer le même fichier : aucun doublon
    assert again["devis_crees"] == [] and again["devis_deja_la"] == [num] and again["conflits"] == []
    with SessionLocal() as db:
        assert db.query(Quotation).filter(Quotation.number == num).count() == 1


def test_meme_numero_autre_contenu_est_un_conflit_rien_n_est_ecrase(c):
    b = _origin(c)
    assert c.post("/api/import/plan-a", json=b).status_code == 200
    other = copy.deepcopy(b)
    other["quotes"][0]["id"] = str(uuid.uuid4())                           # même numéro, autre devis
    other["quotes"][0]["total"] = 1.0
    rep = c.post("/api/import/plan-a", json=other).json()
    assert rep["devis_crees"] == [] and rep["conflits"] and "rien n'est écrasé" in rep["conflits"][0]["raison"]
    with SessionLocal() as db:
        q = db.query(Quotation).filter(Quotation.number == b["quotes"][0]["number"]).one()
        assert q.total != 1.0 and q.id == b["quotes"][0]["id"]


def test_client_connu_par_son_nom_est_reutilise(c):
    b = _origin(c)
    assert c.post("/api/import/plan-a", json=b).status_code == 200
    again = copy.deepcopy(b)                                               # même client, autre identifiant (créé dans une autre session)
    again["customers"][0]["id"] = str(uuid.uuid4())
    again["customers"][0]["code"] = "CL-ZZZZ"
    again["quotes"][0].update(id=str(uuid.uuid4()), number=b["quotes"][0]["number"] + "B", customer_id=again["customers"][0]["id"])
    for i in again["quotes"][0]["items"]:
        i["id"] = str(uuid.uuid4())
    again["invoices"] = []
    rep = c.post("/api/import/plan-a", json=again).json()
    assert rep["clients_reutilises"] == [b["customers"][0]["name"]] and rep["clients_crees"] == []
    with SessionLocal() as db:
        assert db.query(Customer).filter(Customer.name == b["customers"][0]["name"]).count() == 1


@pytest.mark.parametrize("mutate, words", [
    (lambda b: b.update(app="Autre"), "n'est pas un dossier UniC"),
    (lambda b: b.update(format=99), "n'est pas un dossier UniC"),
    (lambda b: b["quotes"][0].update(number="; DROP TABLE"), "numéro invalide"),
    (lambda b: b["quotes"][0].update(id="x"), "identifiant"),
    (lambda b: b["quotes"][0].update(total="abc"), "illisible"),
    (lambda b: b.update(quotes="pas une liste"), "listes attendues"),
])
def test_fichier_trafique_refuse_et_rien_n_est_ecrit(c, mutate, words):
    b = _origin(c)
    mutate(b)
    with SessionLocal() as db:
        before = db.query(Quotation).count()
    r = c.post("/api/import/plan-a", json=b)
    assert r.status_code == 400 and words in r.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Quotation).count() == before


def test_export_depuis_une_date_et_route_fermee_aux_non_admin(c):
    with SessionLocal() as db:
        nothing = planb.export_bundle(db, planb._utc("2999-01-01"))
    assert nothing["quotes"] == [] and nothing["invoices"] == [] and nothing["app"] == "UniC AI"
    assert c.post("/api/import/plan-a", content=b"pas du json").status_code == 400
