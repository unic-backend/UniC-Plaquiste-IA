"""Recherche dans toute la boîte mail : lecture seule, requête neutralisée, résultats gardés en base pour lire et répondre."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import connectors, mailbox  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import InboxMessage  # noqa: E402

RAW = b"From: Awa <awa@ex.sn>\r\nSubject: Devis salon\r\nMessage-ID: <s1@x>\r\nDate: Mon, 1 Sep 2026 10:00:00 +0000\r\n\r\nBonjour, un devis svp."


class Imap:
    folders = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\All) "/" "[Gmail]/Tous les messages"']
    log: list = []
    found = b"3 4"

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def list(self):
        return "OK", self.folders

    def select(self, name, readonly=False):
        Imap.log.append(("select", name, readonly))
        return "OK", [b"1"]

    def search(self, charset, *args):
        Imap.log.append(("search", charset) + args)
        return "OK", [Imap.found]

    def fetch(self, num, what):
        Imap.log.append(("fetch", num, what))
        return "OK", [(b"1 (BODY[] {10}", RAW)]


@pytest.fixture(scope="module", autouse=True)
def booted():
    with TestClient(app):   # crée les tables
        yield


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    Imap.log = []
    Imap.found = b"3 4"
    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", Imap)
    monkeypatch.setattr(mailbox, "_RT", {"user": "p@gmail.com", "password": "pw"})


def test_gmail_search_uses_all_mail_read_only_and_peek():
    rows = mailbox.search("from:awa devis", 10)
    assert ("select", '"[Gmail]/Tous les messages"', True) in Imap.log   # tous les messages, lecture seule
    assert ("search", "UTF-8", "X-GM-RAW", '"from:awa devis"') in Imap.log
    assert all(c[2] == "(BODY.PEEK[])" for c in Imap.log if c[0] == "fetch")   # jamais marqué lu
    assert len(rows) == 2 and rows[0]["subject"] == "Devis salon" and rows[0]["uid"] == "<s1@x>"


def test_search_limit_keeps_the_newest_and_is_capped():
    Imap.found = b" ".join(str(i).encode() for i in range(1, 60))
    assert len(mailbox.search("devis", 5)) == 5
    assert len(mailbox.search("devis", 999)) == 25


def test_search_text_cannot_break_out_of_the_imap_command():
    mailbox.search('x" OR ALL\r\nA1 DELETE INBOX \\', 5)
    sent = [c for c in Imap.log if c[0] == "search"][0][-1]
    assert "\r" not in sent and "\n" not in sent
    # lue comme le fait IMAP (barre = échappement), la chaîne se termine exactement à son dernier caractère : un seul argument
    i, closed_at = 1, None
    assert sent[0] == '"'
    while i < len(sent):
        if sent[i] == "\\":
            i += 2
            continue
        if sent[i] == '"':
            closed_at = i
            break
        i += 1
    assert closed_at == len(sent) - 1


def test_non_gmail_provider_searches_subject_from_and_body(monkeypatch):
    monkeypatch.setattr(mailbox.settings, "imap_host", "mail.exemple.sn")
    monkeypatch.setattr(mailbox.settings, "imap_user", "u")
    monkeypatch.setattr(mailbox.settings, "imap_password", "p")
    mailbox.search("devis", 5)
    assert ("search", "UTF-8", "OR", "OR", "SUBJECT", '"devis"', "FROM", '"devis"', "BODY", '"devis"') in Imap.log
    assert ("select", "INBOX", True) in Imap.log


def test_connector_keeps_results_without_duplicating(monkeypatch):
    monkeypatch.setattr(mailbox, "imap_configured", lambda: True)
    monkeypatch.setattr(mailbox, "search", lambda q, n: [
        {"uid": "<ms1@x>", "from_addr": "awa@ex.sn", "subject": "Devis salon", "date": "", "body": "texte"}])
    db = SessionLocal()
    try:
        a = connectors.search_inbox(db, "devis", 5)
        b = connectors.search_inbox(db, "devis", 5)
        assert a[0].id == b[0].id
        assert db.query(InboxMessage).filter(InboxMessage.uid == "<ms1@x>").count() == 1
    finally:
        db.close()


def test_connector_refuses_empty_query_and_unconfigured_mailbox(monkeypatch):
    db = SessionLocal()
    try:
        monkeypatch.setattr(mailbox, "imap_configured", lambda: False)
        with pytest.raises(connectors.ConnectorError):
            connectors.search_inbox(db, "devis")
        monkeypatch.setattr(mailbox, "imap_configured", lambda: True)
        with pytest.raises(connectors.ConnectorError):
            connectors.search_inbox(db, "   ")
    finally:
        db.close()


def test_connector_reports_imap_failure_without_leaking_details(monkeypatch):
    monkeypatch.setattr(mailbox, "imap_configured", lambda: True)
    monkeypatch.setattr(mailbox, "search", lambda q, n: (_ for _ in ()).throw(RuntimeError("secret-host pw=abc")))
    db = SessionLocal()
    try:
        with pytest.raises(connectors.ConnectorError) as e:
            connectors.search_inbox(db, "devis")
        assert "abc" not in str(e.value)
    finally:
        db.close()


def test_search_endpoint_returns_found_mails_and_validates_input(monkeypatch):
    monkeypatch.setattr(mailbox, "imap_configured", lambda: True)
    monkeypatch.setattr(mailbox, "search", lambda q, n: [
        {"uid": "<ep1@x>", "from_addr": "awa@ex.sn", "subject": "Devis salon", "date": "", "body": "Bonjour"}])
    with TestClient(app) as c:
        r = c.get("/api/mail/search", params={"q": "devis"})
        assert r.status_code == 200 and r.json()[0]["subject"] == "Devis salon" and r.json()[0]["id"]
        assert c.get("/api/mail/search", params={"q": ""}).status_code == 422
        assert c.get("/api/mail/search", params={"q": "x" * 201}).status_code == 422
        assert c.get("/api/mail/search", params={"q": "a", "limit": 99}).status_code == 422
        monkeypatch.setattr(mailbox, "imap_configured", lambda: False)
        assert c.get("/api/mail/search", params={"q": "devis"}).status_code >= 400


def test_agent_tool_is_declared_untrusted_and_dispatchable():
    from app import agent, agents
    names = {t["name"] for t in agent.TOOLS}
    assert "search_inbox" in names
    assert "search_inbox" in agent.UNTRUSTED_SOURCES        # contenu de tiers : consignes cachées jamais suivies
    assert "search_inbox" in agents.SAFE_TOOLS              # lecture seule : permis aux agents planifiés
    assert hasattr(agent.AgentSession, "_t_search_inbox")
    schema = next(t for t in agent.TOOLS if t["name"] == "search_inbox")["input_schema"]
    assert schema["required"] == ["query"] and schema["properties"]["limit"]["maximum"] == 25
