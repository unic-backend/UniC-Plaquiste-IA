"""Étape 6 du diagnostic : les fichiers (plans, photos, documents reçus) partent aussi hors du serveur ; le patron est
prévenu quand la dépense IA s'emballe ou que le crédit s'épuise."""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import alerts, backup, main, usage
from app.config import settings
from app.database import SessionLocal
from app.models import AppSetting, Incident, UsageLog


class _Box:
    """Boîte IMAP simulée : garde chaque dépôt (dossier, message)."""
    sent: list = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, u, p): pass
    def create(self, f): pass
    def append(self, folder, flags, t, data):
        _Box.sent.append((folder, data))
        return "OK", [b""]
    def select(self, f): return "OK", [b"1"]
    def search(self, *a): return "OK", [b""]
    def close(self): pass


def _zips(folder: str) -> list[zipfile.ZipFile]:
    import email
    out = []
    for f, data in _Box.sent:
        if f != folder:
            continue
        for part in email.message_from_bytes(data).walk():
            if part.get_content_type() == "application/zip":
                out.append(zipfile.ZipFile(io.BytesIO(part.get_payload(decode=True))))
    return out


@pytest.fixture
def box(monkeypatch):
    _Box.sent = []
    monkeypatch.setattr(backup.imaplib, "IMAP4_SSL", _Box)
    monkeypatch.setattr(backup.mailbox, "_imap", lambda: ("imap.gmail.com", 993, "moi@gmail.com", "pwd"))
    backup._index_file().unlink(missing_ok=True)
    return _Box


def test_les_fichiers_recus_partent_dans_gmail_seulement_ce_qui_a_change(box):
    plan = settings.uploads_path / "etape6" / "plan_client.pdf"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_bytes(b"%PDF-plan du client")
    devis = settings.artifacts_path / "quotes" / "UniC_Devis_etape6.pdf"
    devis.parent.mkdir(parents=True, exist_ok=True)
    devis.write_bytes(b"%PDF-se refait depuis la base")
    out = backup.push_files_offsite()
    assert out["ok"] and out["files"] >= 1 and out["parts"] >= 1
    names = {n for z in _zips(backup.FILES_FOLDER) for n in z.namelist()}
    assert "files/uploads/etape6/plan_client.pdf" in names
    assert not any("quotes/" in n for n in names)                              # PDF de devis : régénéré, pas copié
    assert backup.status().get("last_files")

    box.sent = []
    assert backup.push_files_offsite()["files"] == 0 and box.sent == []         # rien de neuf : rien ne part
    plan.write_bytes(b"%PDF-plan du client, version 2 plus longue")
    assert backup.push_files_offsite()["files"] == 1                            # modifié : renvoyé seul


def test_un_paquet_de_fichiers_se_restaure_sans_toucher_a_la_base(box, monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    photo = settings.uploads_path / "etape6" / "photo_chantier.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"\xff\xd8photo")
    backup.push_files_offsite()
    pack = next(z for z in _zips(backup.FILES_FOLDER) if "files/uploads/etape6/photo_chantier.jpg" in z.namelist())
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        for n in pack.namelist():
            z.writestr(n, pack.read(n))
    photo.unlink()                                                              # disque perdu
    with TestClient(main.app) as c:
        r = c.post("/api/backups/restore", files={"file": ("UniC_Sauvegarde_Fichiers_x.zip", raw.getvalue(), "application/zip")})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "files" and r.json()["restored_files"] >= 1 and "safety_backup" not in r.json()
        assert photo.read_bytes() == b"\xff\xd8photo"
        for evil in ("files/../unic.db", "files/../../etc/x", "files/backups/status.json"):
            bad = io.BytesIO()
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr(evil, b"x")
                z.writestr("manifest.json", json.dumps({"app": "UniC AI", "kind": "files", "format": 1}))
            r = c.post("/api/backups/restore", files={"file": ("UniC_Sauvegarde_Fichiers_y.zip", bad.getvalue(), "application/zip")})
            assert r.status_code == 400, evil                                   # jamais hors des dossiers sauvegardés


def _spend(db, usd: float, when: datetime) -> None:
    db.add(UsageLog(model="claude-sonnet-5-5", input_tokens=1, output_tokens=1, cache_read_tokens=0, cache_write_tokens=0,
                    web_searches=0, cost_usd=usd, price_known=True, created_at=when))


def test_alerte_quand_la_depense_ia_s_emballe_ou_que_le_credit_s_epuise():
    now = datetime(2031, 3, 20, 15, 0, tzinfo=timezone.utc)                     # date à part : pas de mélange avec les autres tests
    with SessionLocal() as db:
        for row in db.query(AppSetting).filter(AppSetting.key.in_(("credit_usd", "credit_since"))).all():
            db.delete(row)
        for d in range(1, 14):
            _spend(db, 1.0, now - timedelta(days=d))                            # 1 $ par jour d'habitude
        _spend(db, 2.5, now - timedelta(hours=2))
        db.commit()
        assert usage.spend_alerts(db, now) == []                                # 2,5 $ < 3 × 1 $ : normal
        _spend(db, 1.0, now - timedelta(hours=1))
        db.commit()
        msgs = usage.spend_alerts(db, now)                                       # 3,5 $ ≥ 3 $ : anormal
        assert len(msgs) == 1 and "3.50 $" in msgs[0] and "1.00 $" in msgs[0]
        usage.set_budget(db, 40.0)
        db.query(AppSetting).filter_by(key="credit_since").one().value = (now - timedelta(days=30)).isoformat()
        db.commit()
        msgs = usage.spend_alerts(db, now)                                       # 40 − 16,5 = 23,5 $ : encore loin
        assert not any("Crédit" in m for m in msgs)
        db.query(AppSetting).filter_by(key="credit_usd").one().value = "18.0"
        db.commit()
        msgs = usage.spend_alerts(db, now)                                       # 18 − 16,5 = 1,5 $ ≤ 10 % : prévenir
        assert any("Crédit IA presque épuisé" in m and "1.50 $" in m for m in msgs)
        for row in db.query(AppSetting).filter(AppSetting.key.in_(("credit_usd", "credit_since"))).all():
            db.delete(row)
        db.commit()


def test_le_tour_d_alertes_transforme_la_depense_en_incident(monkeypatch):
    monkeypatch.setattr(usage, "spend_alerts", lambda db: ["Dépense IA inhabituelle aujourd'hui : 9.00 $ estimés."])
    with SessionLocal() as db:
        alerts.tick(db)
        row = db.query(Incident).filter(Incident.kind == "budget").order_by(Incident.last_at.desc()).first()
        assert row is not None and row.source.startswith("dépenses IA ") and "9.00 $" in row.message
        assert alerts.KIND_LABEL["budget"] == "dépenses IA"
