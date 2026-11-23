"""Google Drive du patron : options coupées par défaut, dépôt sans doublon, erreurs lisibles, jamais bloquant pour un devis."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import google_business as gb, google_drive as gd  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app import main as server  # noqa: E402
from app.models import AppSetting  # noqa: E402

server.startup()   # tables et réglages (idempotent)


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data or {}
        self.content = b"x" if data is not None else b""

    def json(self):
        return self._data


class FakeDrive:
    """Faux Google Drive en mémoire : dossiers et fichiers par (parent, nom)."""
    files: dict = {}
    calls: list = []
    deny = False

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None):
        return Resp(200, {"access_token": "tok", "expires_in": 3600})

    def request(self, method, url, headers=None, params=None, json=None, content=None):
        FakeDrive.calls.append((method, url))
        if FakeDrive.deny:
            return Resp(403, {})
        q = (params or {}).get("q", "")
        if method == "GET":
            hits = [fid for (parent, name), fid in FakeDrive.files.items() if f"name = '{name}'" in q and f"'{parent}' in parents" in q]
            return Resp(200, {"files": [{"id": h} for h in hits[:1]]})
        if method == "POST" and json is not None:   # dossier
            fid = f"F{len(FakeDrive.files)}"
            FakeDrive.files[(json["parents"][0], json["name"])] = fid
            return Resp(200, {"id": fid})
        if method == "POST":   # fichier (multipart)
            body = content.decode("latin-1")
            name = body.split('"name": "')[1].split('"')[0]
            parent = body.split('"parents": ["')[1].split('"')[0]
            fid = f"D{len(FakeDrive.files)}"
            FakeDrive.files[(parent, name)] = fid
            return Resp(200, {"id": fid})
        if method == "PATCH":
            return Resp(200, {"id": url.rsplit("/", 1)[1]})
        return Resp(404, {})


@pytest.fixture()
def drive(monkeypatch):
    FakeDrive.files, FakeDrive.calls, FakeDrive.deny = {}, [], False
    gd._folders.clear()
    gd._state.update(last_ok="", last_error="")
    monkeypatch.setattr(gd.httpx, "Client", FakeDrive)
    gb.set_runtime({"google_client_id": "cid.apps.googleusercontent.com", "google_client_secret": "s" * 12,
                    "google_refresh_token": "r" * 24})
    with SessionLocal() as db:
        for k in gd.OPTIONS:
            row = db.get(AppSetting, k)
            if row:
                db.delete(row)
        db.commit()
    yield
    gb.set_runtime(None)


def test_options_coupees_par_defaut(drive):
    with SessionLocal() as db:
        st = gd.status(db)
        assert st["available"] and not any(st["options"].values())
        assert gd.push_document(db, Path(__file__), "quotation", "TOUSHA GROUP", "devis.pdf") is False
    assert FakeDrive.calls == []   # rien ne part sans le clic du patron


def test_depot_range_par_client_sans_doublon(drive, tmp_path):
    pdf = tmp_path / "UniC_Devis.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with SessionLocal() as db:
        gd.set_options(db, {"drive_docs": True, "inconnue": True})
        assert set(k for k, v in gd.status(db)["options"].items() if v) == {"drive_docs"}
        assert gd.push_document(db, pdf, "quotation", "TOUSHA GROUP", pdf.name) is True
        assert gd.push_document(db, pdf, "quotation", "TOUSHA GROUP", pdf.name) is True   # PDF refait
    names = {name for (_parent, name) in FakeDrive.files}
    assert {"UniC IA", "Devis", "TOUSHA GROUP", "UniC_Devis.pdf"} <= names
    assert sum(1 for (_p, n) in FakeDrive.files if n == "UniC_Devis.pdf") == 1
    assert sum(1 for m, _u in FakeDrive.calls if m == "PATCH") == 1   # 2e dépôt : contenu remplacé
    assert gd._state["last_ok"] and not gd._state["last_error"]


def test_refus_google_message_lisible_jamais_bloquant(drive, tmp_path):
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(b"%PDF")
    FakeDrive.deny = True
    with SessionLocal() as db:
        gd.set_options(db, {"drive_docs": True})
        assert gd.push_document(db, pdf, "invoice", "", pdf.name) is True   # pas d'exception
    assert "drive.file" in gd._state["last_error"]


def test_photos_lecture_seule_et_option(drive):
    with SessionLocal() as db:
        with pytest.raises(gd.DriveError):
            gd.list_photos(db, "Cloisons")
        gd.set_options(db, {"drive_photos": True})
        assert gd.list_photos(db, "Dossier introuvable") == []
    assert all(m == "GET" for m, _u in FakeDrive.calls)


def test_nom_avec_apostrophe_echappe():
    assert gd._q("l'atelier") == "l\\'atelier"
    assert gd._clean("a/b\\c") == "a b c"
