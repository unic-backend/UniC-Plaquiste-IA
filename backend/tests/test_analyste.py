"""Analyste d'entreprise : les vrais chiffres d'une période (encaissé sans double compte, signé, facturé, dépenses, résultat),
comparés à la période d'avant, avec des points d'attention tirés par des règles fixes, un PDF avec graphique et l'outil du chat."""
from datetime import datetime, timezone

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app import analyste, claims, margin
from app.agent import AgentSession
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Expense, Invoice, Payment, Quotation, Receipt

NOW = datetime(2031, 6, 15, 12, tzinfo=timezone.utc)   # loin des données des autres tests


def at(month: int, day: int) -> datetime:
    return datetime(2031, month, day, 9, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def data():
    with TestClient(app):
        with SessionLocal() as db:
            def quote(number, who, total, decision, decided):
                q = Quotation(number=number, title="Plafond", client_label=who, status="approved", subtotal=total, total=total,
                              currency="FCFA", client_decision=decision, decided_at=decided, approved_at=decided, created_at=decided)
                db.add(q)
                db.flush()
                return q
            a = quote("UC-ANA-A", "Awa Analyse Diop", 1_000_000, "accepted", at(6, 3))
            b = quote("UC-ANA-B", "Moussa Analyse Fall", 500_000, "accepted", at(5, 10))
            quote("UC-ANA-C", "Awa Analyse Diop", 300_000, "declined", at(6, 7))
            inv = Invoice(number="UC-ANA-F", kind="invoice", quotation_id=a.id, status="partial", currency="FCFA", total=1_000_000,
                          approved_at=at(6, 4), created_at=at(6, 4))
            db.add(inv)
            db.add(Invoice(number="UC-ANA-BR", kind="invoice", quotation_id=b.id, status="draft", total=777_777, created_at=at(6, 5)))
            db.flush()
            mirror = Payment(invoice_id=inv.id, amount=400_000, paid_at=at(6, 5), reference="suivi")
            db.add(mirror)
            db.flush()
            db.add(Receipt(quotation_id=a.id, amount=400_000, received_at=at(6, 5), payment_id=mirror.id))   # versement + son miroir
            db.add(Payment(invoice_id=inv.id, amount=100_000, paid_at=at(6, 10)))                            # payé directement sur la facture
            db.add(Receipt(quotation_id=b.id, amount=500_000, received_at=at(5, 12)))
            db.add(Expense(label="Plaques", amount=700_000, quotation_id=a.id, category="matériaux", spent_at=at(6, 8)))
            db.add(Expense(label="Erreur", amount=999_999, quotation_id=a.id, category="matériaux", spent_at=at(6, 9), status="cancelled"))
            db.add(Expense(label="Camion", amount=100_000, quotation_id=b.id, category="transport", spent_at=at(5, 13)))
            db.commit()
            made = [a.id, b.id]
        yield
        with SessionLocal() as db:   # données du test seulement : retirées pour ne pas fausser les listes des autres tests
            quotes = [q.id for q in db.query(Quotation).filter(Quotation.number.like("UC-ANA-%")).all()]
            invoices = [i.id for i in db.query(Invoice).filter(Invoice.number.like("UC-ANA-%")).all()]
            db.query(Receipt).filter(Receipt.quotation_id.in_(quotes)).delete(synchronize_session=False)
            db.query(Payment).filter(Payment.invoice_id.in_(invoices)).delete(synchronize_session=False)
            db.query(Expense).filter(Expense.quotation_id.in_(made)).delete(synchronize_session=False)
            db.query(Invoice).filter(Invoice.id.in_(invoices)).delete(synchronize_session=False)
            db.query(Quotation).filter(Quotation.id.in_(quotes)).delete(synchronize_session=False)
            db.commit()


def test_periodes_et_comparaisons():
    p = analyste.resolve("ce_mois", now=NOW)
    assert (p["du"], p["au"]) == (at(6, 1).replace(hour=0), NOW)
    assert (p["avant_du"], p["avant_au"]) == (at(5, 1).replace(hour=0), datetime(2031, 5, 15, 12, tzinfo=timezone.utc))   # mêmes jours
    p = analyste.resolve("mois_dernier", now=datetime(2031, 3, 31, tzinfo=timezone.utc))
    assert (p["du"].month, p["au"].month, p["avant_du"].month) == (2, 3, 1)
    p = analyste.resolve("annee_derniere", now=NOW)
    assert (p["du"].year, p["au"].year, p["avant_du"].year) == (2030, 2031, 2029)
    p = analyste.resolve(date_from="2031-06-01", date_to="2031-06-15")
    assert p["au"] == datetime(2031, 6, 16, tzinfo=timezone.utc) and p["label"] == "du 01/06/2031 au 15/06/2031"   # fin incluse
    with pytest.raises(analyste.AnalyseError):
        analyste.resolve(date_from="2031-06-15", date_to="2031-06-01")
    with pytest.raises(analyste.AnalyseError):
        analyste.resolve(date_from="15/06/2031")


def test_les_vrais_chiffres_sans_double_compte(data):
    with SessionLocal() as db:
        margin.set_min_margin(db, 35)
        db.commit()
        try:
            rep = analyste.report(db, "ce_mois", now=NOW)
        finally:
            margin.set_min_margin(db, None)
            db.commit()
    ch = rep["chiffres"]
    assert ch["encaisse"]["valeur"] == 500_000            # 400 000 du suivi (miroir non recompté) + 100 000 payés sur la facture
    assert ch["encaisse"]["avant"] == 500_000 and ch["encaisse"]["evolution_pct"] == 0
    assert ch["signe"]["valeur"] == 1_000_000 and ch["signe"]["evolution_pct"] == 100
    assert ch["facture"]["valeur"] == 1_000_000           # le brouillon ne compte pas
    assert ch["depenses"]["valeur"] == 700_000            # la saisie annulée ne compte pas
    assert ch["resultat"]["valeur"] == -200_000 and ch["taux_acceptation"]["valeur"] == 50
    assert rep["clients"]["top"] == [{"client": "Awa Analyse Diop", "encaisse": 500_000, "part_pct": 100.0}]
    assert rep["depenses_par_categorie"] == [{"categorie": "matériaux", "montant": 700_000, "part_pct": 100.0}]
    site = next(s for s in rep["chantiers"] if s["numero"] == "UC-ANA-A")
    assert site["marge"] == 300_000 and site["marge_pct"] == 30 and site["alerte"]          # sous la marge minimale de 35 %
    june = next(m for m in rep["par_mois"] if m["mois"] == "2031-06")
    assert june["encaisse"] == 500_000 and len(rep["par_mois"]) == 6                         # période courte : 6 mois de tendance
    points = " ".join(rep["points_attention"])
    assert "Dépenses en hausse de 600 %" in points and "Plus de dépenses que d'encaissements" in points
    assert "UC-ANA-A" in points and "Dépendance" not in points                               # un seul client : pas de « dépendance »
    assert not rep["vide"]


def test_periode_vide_et_rapport_pdf(data):
    with SessionLocal() as db:
        empty = analyste.report(db, date_from="2031-01-01", date_to="2031-01-31")
        assert empty["vide"] and empty["chiffres"]["encaisse"]["valeur"] == 0
        art = analyste.to_pdf(db, analyste.report(db, "ce_mois", now=NOW))
        pdf = pdfium.PdfDocument(art.path)
    text = "".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    assert "Bilan" in text and "Points d'attention" in text and "500 000 FCFA" in text and "Mois par mois" in text


def test_l_outil_du_chat_et_l_api(data, monkeypatch):
    with SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("business_report", {"date_from": "2031-06-01", "date_to": "2031-06-15", "pdf": True})
        assert out["chiffres"]["encaisse"]["valeur"] == 500_000 and "ne recalcule rien" in out["note"]
        assert out["pdf"]["fichier"].endswith(".pdf") and len(s.files) == 1
        assert claims.unbacked("Ton rapport PDF est prêt.", s.succeeded) == []           # le PDF a vraiment été créé
        assert "error" in s("business_report", {"date_from": "2031-06-15", "date_to": "2031-06-01"})
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as c:
        r = c.get("/api/analyse", params={"du": "2031-06-01", "au": "2031-06-15"})
        assert r.status_code == 200 and r.json()["chiffres"]["signe"]["valeur"] == 1_000_000
        assert c.get("/api/analyse", params={"du": "2031-06-15", "au": "2031-06-01"}).status_code == 400
        pdf = c.post("/api/analyse/pdf", json={"du": "2031-06-01", "au": "2031-06-15"}).json()
        assert pdf["download_url"].startswith("/api/artifacts/") and c.get(pdf["download_url"]).status_code == 200
