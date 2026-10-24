"""Étape 13 (première partie) : Wave sur les factures et les relances, wolof écrit dans l'interprète, petits défauts corrigés."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import agenda, orchestrator, services as svc, translate
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Artifact, CompanySettings, Invoice, InvoiceItem


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def test_la_date_est_donnee_en_toutes_lettres_par_le_serveur():
    assert agenda.fr_when(datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)) == "jeudi 29 octobre 2026 à 10 h 00"
    assert agenda.fr_when(datetime(2026, 11, 1, 9, 5, tzinfo=timezone.utc)) == "dimanche 1er novembre 2026 à 9 h 05"


@pytest.mark.parametrize("text, briefing", [
    ("mon briefing", True), ("briefing du jour", True), ("fais mon briefing du matin", True), ("résumé de ma journée", True),
    ("Briefing du marché de l'immobilier à Dakar", False), ("fais un briefing sur le prix du ciment", False),
])
def test_le_briefing_ne_capte_plus_une_recherche(text, briefing):
    assert (orchestrator._intent(text, {}) == "briefing") is briefing


def test_wolof_en_texte_seulement():
    assert "wo" in translate.LANGUAGES and "wo" in translate.TEXT_ONLY and "lettres latines" in translate.LANGUAGES["wo"]


def test_wave_sur_la_facture_et_la_relance(c):
    assert c.put("/api/settings", json={"wave_link": "javascript:alert(1)"}).status_code == 422   # lien https seulement
    r = c.put("/api/settings", json={"wave_number": "77 708 50 92", "wave_link": "https://pay.wave.com/m/M_test/c/sn/"})
    assert r.status_code == 200 and r.json()["wave_number"] == "77 708 50 92"
    with SessionLocal() as db:
        inv = Invoice(number="UC-2026-WAVE-F", status="approved", vat_rate=0.18, subtotal=10000, vat_amount=1800, total=11800,
                      paid=0, remaining=11800, currency="FCFA")
        db.add(inv)
        db.flush()
        db.add(InvoiceItem(invoice_id=inv.id, position=1, description="Plaque", quantity=2, unit="u", unit_price=5000, total=10000))
        db.commit()
        art = svc.generate_invoice_pdf(db, inv, None)
        db.commit()
        text = "".join(p.extract_text() or "" for p in PdfReader(db.get(Artifact, art.id).path).pages)
        assert "Payer par Wave" in text and "77 708 50 92" in text and "pay.wave.com" in text and "Scanne ce code" in text
        msg = svc.balance_message(db, inv, "Awa", "FCFA")
        assert "Paiement Wave possible : numéro 77 708 50 92 · https://pay.wave.com/m/M_test/c/sn/" in msg
        inv.kind = "credit"                                                         # un avoir ne se paie pas
        art = svc.generate_invoice_pdf(db, inv, None)
        db.commit()
        assert "Payer par Wave" not in "".join(p.extract_text() or "" for p in PdfReader(db.get(Artifact, art.id).path).pages)
        row = db.query(CompanySettings).first()
        row.wave_number, row.wave_link = "", ""
        db.commit()
        assert "Wave" not in svc.balance_message(db, inv, "Awa", "FCFA")            # rien de renseigné : rien d'imprimé
