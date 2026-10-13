"""Mise à la corbeille Gmail : la sécurité des mails du patron. Jamais de retrait si la copie vers la corbeille n'a pas réussi."""
import imaplib
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import mailbox  # noqa: E402


class Imap:
    """Faux serveur IMAP configurable ; `log` garde chaque commande envoyée."""
    folders = [b'(\\HasNoChildren) "/" "INBOX"']
    selectable: set = set()
    copy_ok = True
    log: list = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pwd):
        pass

    def list(self):
        return "OK", self.folders

    def select(self, name, readonly=False):
        Imap.log.append(("select", name, readonly))
        if name == "INBOX" or name.strip('"') in self.selectable:
            return "OK", [b"1"]
        return "NO", [b"inconnu"]

    def uid(self, cmd, *args):
        Imap.log.append((cmd,) + args)
        if cmd == "SEARCH":
            return "OK", [b"7"]
        if cmd == "COPY":
            return ("OK" if self.copy_ok else "NO"), [b""]
        return "OK", [b""]

    def expunge(self):
        Imap.log.append("expunge")
        return "OK", []


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    Imap.log = []
    Imap.copy_ok = True
    Imap.selectable = set()
    Imap.folders = [b'(\\HasNoChildren) "/" "INBOX"']
    monkeypatch.setattr(imaplib, "IMAP4_SSL", Imap)
    monkeypatch.setattr(mailbox, "_imap", lambda: ("imap.test", 993, "u@test", "pwd"))


def _cmds():
    return [e[0] for e in Imap.log if isinstance(e, tuple)]


def test_trash_folder_is_found_by_usual_names_when_the_server_gives_no_special_use_flag():
    Imap.selectable = {"[Gmail]/Corbeille"}
    out = mailbox.trash(["<a@x>"])
    assert out["moved"] == ["<a@x>"] and ("COPY", "7", '"[Gmail]/Corbeille"') in Imap.log


def test_no_trash_folder_means_nothing_is_touched():
    with pytest.raises(RuntimeError, match="Corbeille introuvable"):
        mailbox.trash(["<a@x>"])
    assert "COPY" not in _cmds() and "STORE" not in _cmds() and "expunge" not in Imap.log


def test_if_the_copy_to_trash_fails_the_mail_stays_in_the_inbox():
    Imap.folders = [b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"']
    Imap.copy_ok = False
    out = mailbox.trash(["<a@x>"])
    assert out == {"moved": [], "missing": ["<a@x>"]}
    assert "STORE" not in _cmds() and "expunge" not in Imap.log     # pas de drapeau « supprimé », pas de retrait


def test_a_message_id_with_quotes_cannot_break_the_search_command():
    Imap.folders = [b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"']
    mailbox.trash(['<a"b@x> OR ALL'])
    search = next(e for e in Imap.log if isinstance(e, tuple) and e[0] == "SEARCH")
    assert search[-1].count('"') == 2                               # guillemets retirés : la valeur reste UNE chaîne
