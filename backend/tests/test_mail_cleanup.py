"""Nettoyage de la boîte : repérage prudent, corbeille sur clic seulement, jamais de suppression définitive."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mail_cleanup, mailbox  # noqa: E402
from app.main import app  # noqa: E402
from app.models import InboxMessage  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _m(frm, subject, body="", **kw):
    kw.setdefault("uid", f"<{frm}-{subject}>"[:200])
    return InboxMessage(from_addr=frm, subject=subject, body=body, **kw)


def test_classifier_proposes_ads_and_finished_github_but_never_work_or_alerts():
    gh_done = _m("notifications@github.com", "Re: [org/repo] fix(agents) (#74)", "Merged #74 into main.")
    gh_failed = _m("notifications@github.com", "Run failed: Tests - claude/x", "Tests / backend failed")
    gh_review = _m("notifications@github.com", "Re: [org/repo] PR (#80)", "@owner requested your review")
    gh_plain = _m("notifications@github.com", "Re: [org/repo] PR (#81)", "Nouveau commentaire")
    ad = _m("newsletter@boutique.sn", "-30% soldes ce week-end", "Voir l'offre. Pour vous désabonner, cliquez ici.")
    ad_but_invoice = _m("newsletter@boutique.sn", "Votre facture et -30% soldes", "Se désabonner")
    client_mail = _m("client@mail.sn", "Devis plafond salon", "Bonjour, pouvez-vous passer lundi ?")
    lone_noreply = _m("noreply@banque.sn", "Votre relevé", "Bonjour")
    assert mail_cleanup.classify(gh_done)[0] == "GitHub"
    assert mail_cleanup.classify(ad)[0] == "Publicité"
    for keep in (gh_failed, gh_review, gh_plain, ad_but_invoice, client_mail, lone_noreply):
        assert mail_cleanup.classify(keep) is None, keep.subject


class _TrashImap:
    log = []
    folders = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Corbeille"']

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pwd):
        _TrashImap.log.append("login")

    def list(self):
        return "OK", self.folders

    def select(self, name, readonly=False):
        _TrashImap.log.append(("select", name, readonly))
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        _TrashImap.log.append((cmd,) + args)
        if cmd == "SEARCH":
            return "OK", [b"41" if "<known@x>" in args[-1] else b""]
        return "OK", [b""]

    def expunge(self):
        _TrashImap.log.append("expunge")
        return "OK", []


def test_trash_copies_to_the_trash_folder_first_then_removes_from_inbox(monkeypatch):
    import imaplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _TrashImap)
    _TrashImap.log.clear()
    out = mailbox.trash(["<known@x>", "<gone@x>"])
    assert out == {"moved": ["<known@x>"], "missing": ["<gone@x>"]}
    cmds = [e[0] for e in _TrashImap.log if isinstance(e, tuple)]
    assert cmds.index("COPY") < cmds.index("STORE")                                         # copie d'abord : jamais de perte
    assert ("COPY", "41", '"[Gmail]/Corbeille"') in _TrashImap.log                           # corbeille repérée par son attribut, pas par la langue
    assert "expunge" in _TrashImap.log


def test_endpoint_trashes_only_proposed_mails_on_click_and_forgets_them_locally(client, monkeypatch):
    from app.database import SessionLocal
    db = SessionLocal()
    db.query(InboxMessage).delete()
    ad = _m("newsletter@promo.sn", "Promo -40% soldes", "Pour vous désabonner cliquez ici", uid="<ad@x>")
    work = _m("client@mail.sn", "Devis cloison", "Bonjour", uid="<work@x>")
    db.add_all([ad, work])
    db.commit()
    ad_id, work_id = ad.id, work.id
    db.close()
    cands = client.get("/api/mail/cleanup").json()["candidates"]
    assert [c["id"] for c in cands] == [ad_id]                                              # le mail de travail n'est jamais proposé
    sent = []
    monkeypatch.setattr(mailbox, "trash", lambda ids: sent.append(ids) or {"moved": list(ids), "missing": []})
    assert client.post("/api/mail/cleanup/trash", json={"ids": [work_id]}).status_code == 400   # hors liste : refusé
    assert not sent
    ok = client.post("/api/mail/cleanup/trash", json={"ids": [ad_id, work_id]}).json()
    assert ok["trashed"] == 1 and sent == [["<ad@x>"]]                                       # seul le mail proposé part, jamais l'autre
    ids = [m["id"] for m in client.get("/api/mail").json()]
    assert ad_id not in ids and work_id in ids


def test_gmail_failure_touches_nothing_and_keeps_the_mail(client, monkeypatch):
    from app.database import SessionLocal
    db = SessionLocal()
    db.query(InboxMessage).delete()
    ad = _m("newsletter@promo.sn", "Promo -40% soldes", "Pour vous désabonner cliquez ici", uid="<ad2@x>")
    db.add(ad)
    db.commit()
    ad_id = ad.id
    db.close()

    def boom(ids):
        raise RuntimeError("Dossier Corbeille introuvable sur ce compte : rien n'a été touché.")
    monkeypatch.setattr(mailbox, "trash", boom)
    r = client.post("/api/mail/cleanup/trash", json={"ids": [ad_id]})
    assert r.status_code == 502 and "rien n'a été touché" in r.json()["detail"]
    assert ad_id in [m["id"] for m in client.get("/api/mail").json()]


def test_agents_have_no_way_to_trash_mail():
    from app import agents
    assert not any("trash" in t or "cleanup" in t or "corbeille" in t for t in agents.SAFE_TOOLS)
