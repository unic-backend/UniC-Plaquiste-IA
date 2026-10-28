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


class _Gmail:
    """Boîte Gmail simulée : « Tous les messages » voit tout ; COPY vers la corbeille, \\Deleted + EXPUNGE retirent."""
    msgs: list = []      # dicts : uid, sender, subject, files, trashed, deleted
    copied: list = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, u, p): pass
    def create(self, f): pass
    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/Tous les messages"',
                      b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Corbeille"']
    def append(self, folder, flags, t, data):
        m = email.message_from_bytes(data)
        _Gmail._add(str(m["From"]), str(m["Subject"]), [pt.get_filename() for pt in m.walk() if pt.get_filename()])
        return "OK", [b""]
    @classmethod
    def _add(cls, sender, subject, files):
        cls.msgs.append({"uid": len(cls.msgs) + 1, "sender": sender, "subject": subject, "files": files, "trashed": False, "deleted": False})
    def select(self, f):
        self.folder = f
        return "OK", [b"1"]
    def search(self, *a): return "OK", [b""]
    def _live(self):
        return [m for m in _Gmail.msgs if not m["trashed"]]
    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            sender, subject = args[2].strip('"'), args[4].strip('"')
            return "OK", [b" ".join(str(m["uid"]).encode() for m in self._live() if m["sender"] == sender and subject in m["subject"])]
        ids = {int(x) for x in args[0].split(b",")}
        if cmd == "FETCH":
            return "OK", [f'{m["uid"]} (UID {m["uid"]} BODYSTRUCTURE (("text" "plain" NIL NIL NIL "7bit" 1 1)'.encode()
                          + b"".join(f' ("application" "zip" ("name" "{f}") NIL NIL "base64" 10)'.encode() for f in m["files"]) + b' "mixed"))'
                          for m in _Gmail.msgs if m["uid"] in ids]
        if cmd == "COPY":
            _Gmail.copied.append((sorted(ids), args[1]))
        if cmd == "STORE":
            for m in _Gmail.msgs:
                if m["uid"] in ids:
                    m["deleted"] = True
        return "OK", [b""]
    def expunge(self):
        for m in _Gmail.msgs:
            if m["deleted"]:
                m["trashed"] = True
        return "OK", [b""]
    def close(self): pass


def test_anciennes_copies_non_chiffrees_a_la_corbeille_apres_un_renvoi_chiffre(c, monkeypatch):
    _Gmail.msgs, _Gmail.copied = [], []
    monkeypatch.setattr(backup.imaplib, "IMAP4_SSL", _Gmail)
    me = "moi@gmail.com"
    _Gmail._add(me, "Sauvegarde UniC AI — 2026-10-20", ["UniC_Sauvegarde_2026-10-20.zip"])                 # en clair : à la corbeille
    _Gmail._add(me, "Fichiers UniC AI — 2026-10-20 (3)", ["UniC_Sauvegarde_Fichiers_2026-10-20_1.zip"])     # en clair : à la corbeille
    _Gmail._add(me, "Sauvegarde UniC AI — 2026-10-27", ["UniC_Sauvegarde_2026-10-27.zip.enc"])             # déjà chiffrée : gardée
    _Gmail._add("arnaque@exemple.com", "Sauvegarde UniC AI — piège", ["UniC_Sauvegarde_piege.zip"])       # pas de nous : gardée
    _Gmail._add(me, "Devis Mme Fall", ["devis.pdf"])                                                        # autre courrier : gardé
    assert c.post("/api/backups/purge-plain").status_code == 400                                           # chiffrement pas actif : rien
    assert not any(m["trashed"] for m in _Gmail.msgs)

    c.put("/api/backups/password", json={"password": PASSWORD})
    f = settings.storage_path / "uploads" / "nettoyage" / "photo.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("photo du plafond", encoding="utf-8")
    out = c.post("/api/backups/purge-plain").json()
    assert out["ok"] and out["trashed"] == 2 and out["to_trash"] and out["files_resent"] >= 1
    gone = {m["subject"] for m in _Gmail.msgs if m["trashed"]}
    assert gone == {"Sauvegarde UniC AI — 2026-10-20", "Fichiers UniC AI — 2026-10-20 (3)"}
    assert _Gmail.copied and all(dest == '"[Gmail]/Corbeille"' for _ids, dest in _Gmail.copied)
    sent = [m for m in _Gmail.msgs if m["uid"] > 5]                                                       # renvoyés AVANT le nettoyage
    assert sent and all(n.endswith(".enc") for m in sent for n in m["files"]) and not any(m["trashed"] for m in sent)
    assert c.post("/api/backups/purge-plain").json()["trashed"] == 0                                       # plus rien en clair
    with SessionLocal() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "backup_purge_plain").count() == 2


def test_dossiers_speciaux_et_pieces_jointes_lus_quelle_que_soit_la_langue():
    box = _Gmail()
    assert backup._special_folders(box) == {"\\All": '"[Gmail]/Tous les messages"', "\\Trash": '"[Gmail]/Corbeille"'}
    rows = [(b'1 (UID 9 BODYSTRUCTURE (("application" "zip" ("name" {28}', b'UniC_Sauvegarde_x.zip.enc"'), b'))',
            b'2 (UID 10 BODYSTRUCTURE (("text" "plain") ("application" "zip" ("name" "UniC_Sauvegarde_y.zip")) "mixed"))']
    assert backup._attachment_names(rows)[1] == (b"10", ["UniC_Sauvegarde_y.zip"])
