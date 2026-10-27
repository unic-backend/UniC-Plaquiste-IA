"""Sauvegardes chiffrées : avec un mot de passe des sauvegardes, les copies déposées dans Gmail sont illisibles sans lui
(Gmail piraté = rien à lire). Le mot de passe n'est écrit nulle part ; un nouveau serveur restaure avec lui ; sans mot de passe
choisi, rien ne change (copies .zip comme avant)."""
import email
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import backup
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, Customer

PASSWORD = "Phrase-de-test-42"   # mot de passe de TEST (jamais celui du patron)


class _Box:
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


def _attachments(folder: str) -> list[tuple[str, bytes]]:
    out = []
    for f, data in _Box.sent:
        if f == folder:
            for part in email.message_from_bytes(data).walk():
                if part.get_filename():
                    out.append((part.get_filename(), part.get_payload(decode=True)))
    return out


@pytest.fixture
def c(monkeypatch):
    _Box.sent = []
    monkeypatch.setattr(settings, "unic_access_code", "")
    monkeypatch.setattr(backup.imaplib, "IMAP4_SSL", _Box)
    monkeypatch.setattr(backup.mailbox, "_imap", lambda: ("imap.gmail.com", 993, "moi@gmail.com", "pwd"))
    backup.clear_password()
    with TestClient(app) as client:
        yield client
    backup.clear_password()   # les autres tests gardent des copies non chiffrées


def test_sans_mot_de_passe_rien_ne_change(c):
    assert c.get("/api/backups").json()["encrypted"] is False
    made = backup.create("test")
    backup.push_offsite(made["name"])
    name, data = _attachments(backup.REMOTE_FOLDER)[-1]
    assert name == made["name"] and zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_copie_gmail_chiffree_et_restauree_sur_un_nouveau_serveur(c):
    assert c.put("/api/backups/password", json={"password": "court"}).status_code == 400
    assert c.put("/api/backups/password", json={"password": PASSWORD}).json() == {"encrypted": True}
    assert c.get("/api/backups").json()["encrypted"] is True
    kept = backup._key_file().read_text(encoding="utf-8")
    assert PASSWORD not in kept and backup._stored()[1].hex() not in kept       # ni le mot de passe ni la clé en clair

    with SessionLocal() as db:
        db.add(Customer(code="ENC1", name="Client Chiffré"))
        db.commit()
    made = backup.create("test")
    assert ".backup_key.json" not in zipfile.ZipFile(backup.path_of(made["name"])).namelist()
    backup.push_offsite(made["name"])
    name, data = _attachments(backup.REMOTE_FOLDER)[-1]
    assert name == made["name"] + ".enc" and data.startswith(backup.ENC_MAGIC)
    assert b"SQLite format" not in data and b"manifest.json" not in data and b"Client Chiff" not in data   # illisible
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(data))

    with SessionLocal() as db:   # perte de données…
        db.query(Customer).filter(Customer.code == "ENC1").delete()
        db.commit()
    r = c.post("/api/backups/restore", files={"file": (name, data, "application/octet-stream")})   # même serveur : sa clé suffit
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(Customer).filter(Customer.code == "ENC1").first() is not None

    backup.clear_password()   # nouveau serveur : il n'a pas la clé
    r = c.post("/api/backups/restore", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 400 and r.json()["detail"] == backup.NEED_PASSWORD
    r = c.post("/api/backups/restore", files={"file": (name, data, "application/octet-stream")}, data={"password": "Mauvais-mot-99"})
    assert r.status_code == 400 and "incorrect" in r.json()["detail"]
    r = c.post("/api/backups/restore", files={"file": (name, data, "application/octet-stream")}, data={"password": PASSWORD})
    assert r.status_code == 200, r.text
    tampered = data[:-5] + bytes(b ^ 1 for b in data[-5:])
    r = c.post("/api/backups/restore", files={"file": (name, tampered, "application/octet-stream")}, data={"password": PASSWORD})
    assert r.status_code == 400                                                    # fichier modifié : refusé, rien n'est changé


def test_paquets_de_fichiers_chiffres_et_journal(c):
    c.put("/api/backups/password", json={"password": PASSWORD})
    backup._index_file().unlink(missing_ok=True)
    f = settings.storage_path / "uploads" / "chiffre" / "plan_secret.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("plan du chantier de Mme Fall", encoding="utf-8")
    backup.push_files_offsite()
    packs = [(n, d) for n, d in _attachments(backup.FILES_FOLDER) if n.endswith(".enc")]
    assert packs and all(b"plan du chantier" not in d and b"plan_secret" not in d for _n, d in packs)
    out = backup.restore(next(d for n, d in packs), "")
    assert out["kind"] == "files" and out["restored_files"] >= 1
    assert c.delete("/api/backups/password").json() == {"encrypted": False}
    with SessionLocal() as db:
        acts = [a.entity_id for a in db.query(AuditLog).filter(AuditLog.action == "backup_password").all()]
    assert "on" in acts and "off" in acts
