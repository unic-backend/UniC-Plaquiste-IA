"""Devis du Drive → devis de l'appli : lecture exacte du PDF UniC, refus d'un PDF étranger ou faux, import unique, acceptation."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import drive_quotes, services
from app.database import SessionLocal
from app.main import app
from app.models import Artifact, Quotation

LINES = [
    {"name": "Plaque de plâtre BA13 2000×1200", "quantity": 10, "unit": "u", "sku": "BA13-2000x1200", "status": "confirmed"},
    {"name": "Lambris PVC blanc 2,90 m × 15 cm", "quantity": 69, "unit": "lame", "fixed_price": 3500, "status": "confirmed"},
    {"name": "Livraison", "quantity": 1, "unit": "forfait", "fixed_price": 30000, "status": "confirmed"},
    {"name": "Main-d'œuvre — pose déco BA13 et lambris", "quantity": 1, "unit": "forfait", "fixed_price": 350000, "status": "confirmed"},
]


@pytest.fixture
def c():
    with TestClient(app) as client:
        yield client


def _pdf() -> tuple[bytes, float]:
    with SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="", quantities=LINES, customer_id=None, project_id=None, user_id=None,
                                               client_name="Global Bridge", lieu="Cité Keur Gorgui", objet="Pose déco et lambris", vat_rate=None)
        return Path(db.get(Artifact, q.artifact_id).path).read_bytes(), q.total


def test_lecture_exacte_du_pdf(c):
    data, total = _pdf()
    p = drive_quotes.parse_quote_pdf(data)
    assert p["client"] == "Global Bridge" and p["lieu"] == "Cité Keur Gorgui" and p["total"] == total
    assert [r["quantity"] for r in p["materials"]] == [10, 69, 1] and p["materials"][1]["unit_price"] == 3500
    assert p["labour"][0]["total"] == 350000 and p["vat_rate"] is None


def test_refus_pdf_etranger():
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO(); cv = canvas.Canvas(buf); cv.drawString(100, 750, "Facture quelconque 123"); cv.save()
    with pytest.raises(drive_quotes.DriveError):
        drive_quotes.parse_quote_pdf(buf.getvalue())


def test_import_unique_puis_accepte(c, monkeypatch):
    data, total = _pdf()
    monkeypatch.setattr(drive_quotes, "download", lambda db, fid: ("Devis_UC-X_Global_Bridge.pdf", data))
    r = c.post("/api/drive/quotes/FICHIER_TEST_123/import", json={"accepted": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] == total and out["already"] is False and out["decision"]
    with SessionLocal() as db:
        q = db.get(Quotation, out["id"])
        assert q.client_decision == "accepted" and q.artifact_id and "Importé depuis Google Drive" in q.notes
        assert {i.description for i in q.items} >= {"Lambris PVC blanc 2,90 m × 15 cm", "Main-d'œuvre — pose déco BA13 et lambris"}
    again = c.post("/api/drive/quotes/FICHIER_TEST_123/import", json={}).json()
    assert again["already"] is True and again["id"] == out["id"]


def test_sans_connexion(c):
    r = c.get("/api/drive/quotes")
    assert r.status_code == 400 and "pas connecté" in r.json()["detail"]
    assert c.get("/api/drive/account").json()["connected"] is False


def test_devis_absent_renvoie_vers_le_drive(monkeypatch):
    from app import agent as ag
    from app.database import SessionLocal
    monkeypatch.setattr(drive_quotes, "status", lambda db: {"connected": True})
    with SessionLocal() as db:
        out = ag.AgentSession(db, None, {"owner_message": "Madame Ribero a accepté"})(
            "mark_quote_decision", {"decision": "accepted", "client": "Madame Ribero Inconnue"})
        assert "import_drive_quote" in out["error"]


def test_copie_pdf_nouveau_puis_remplace(monkeypatch):
    calls = []

    class R:
        def __init__(self, code, js=None): self.status_code, self._js = code, js or {}
        def json(self): return self._js

    monkeypatch.setattr(drive_quotes, "_token", lambda *a: "tok")
    monkeypatch.setattr(drive_quotes.httpx, "post", lambda url, **kw: calls.append(("post", kw["headers"]["Content-Type"], kw["content"])) or R(200, {"id": "F123"}))
    monkeypatch.setattr(drive_quotes.httpx, "patch", lambda url, **kw: calls.append(("patch", url)) or R(200))
    assert drive_quotes.push_pdf(("a", "b", "c"), b"%PDF-1.4 x", "Devis_UC-1_Awa.pdf") == "F123"
    assert calls[0][1].startswith("multipart/related") and b'"Devis_UC-1_Awa.pdf"' in calls[0][2] and b"%PDF-1.4 x" in calls[0][2]
    assert drive_quotes.push_pdf(("a", "b", "c"), b"%PDF v2", "x.pdf", "F123") == "F123" and calls[1] == ("patch", f"{drive_quotes.UPLOAD}/F123")


def test_copie_refusee_message_clair(monkeypatch):
    class R:
        status_code = 403
        def json(self): return {}
    monkeypatch.setattr(drive_quotes, "_token", lambda *a: "tok")
    monkeypatch.setattr(drive_quotes.httpx, "post", lambda url, **kw: R())
    with pytest.raises(drive_quotes.DriveError, match="drive.file"):
        drive_quotes.push_pdf(("a", "b", "c"), b"%PDF", "x.pdf")


def test_livraison_a_la_charge_du_client_importable(c):
    """Sans prix de livraison, l'appli ajoute « Livraison : à la charge du client » écrite « — » : la ligne se lit à 0."""
    with SessionLocal() as db:
        q = services.quotation_from_quantities(db, title="", quantities=[LINES[1], LINES[3]], customer_id=None, project_id=None,
                                               user_id=None, client_name="Catherine", lieu=None, objet="Plafond", vat_rate=None)
        data, total = Path(db.get(Artifact, q.artifact_id).path).read_bytes(), q.total
    p = drive_quotes.parse_quote_pdf(data)
    assert p["total"] == total and p["materials"][-1]["name"].startswith("Livraison") and p["materials"][-1]["total"] == 0


def test_connexion_dit_quelle_case_corriger(monkeypatch):
    """Erreur de saisie → la case fautive en clair (cas vécu : « Catherine » collé dans l'identifiant client)."""
    called = []
    monkeypatch.setattr(drive_quotes.httpx, "post", lambda *a, **kw: called.append(1))
    with SessionLocal() as db:
        with pytest.raises(drive_quotes.DriveError, match="Identifiant client incorrect"):
            drive_quotes.connect(db, "Catherine", "GOCSPX-x", "1//x")
    assert not called   # rien n'est envoyé à Google

    class R:
        status_code = 400
        def __init__(self, err): self.err = err
        def json(self): return {"error": self.err}
    for err, words in (("invalid_client", "identifiant client ou le secret"), ("unauthorized_client", "autre identifiant client"),
                       ("invalid_grant", "refresh token est refusé"), ("autre", "Recopie")):
        monkeypatch.setattr(drive_quotes.httpx, "post", lambda *a, err=err, **kw: R(err))
        with SessionLocal() as db, pytest.raises(drive_quotes.DriveError, match=words):
            drive_quotes.connect(db, "123-abc.apps.googleusercontent.com", "GOCSPX-x", "1//x")
