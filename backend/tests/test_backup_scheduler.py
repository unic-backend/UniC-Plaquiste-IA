"""Le fil de sauvegarde automatique ne démarre pas pendant les tests (il créait des sauvegardes à un moment imprévisible)."""
import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import backup  # noqa: E402
from app.main import app  # noqa: E402


def test_no_backup_thread_is_started_when_background_work_is_disabled():
    before = {t.name for t in threading.enumerate()}
    backup.start_scheduler()
    with TestClient(app):                          # le démarrage de l'appli appelle aussi start_scheduler()
        pass
    new = {t.name for t in threading.enumerate()} - before
    assert "unic-backup" not in new and not any(t.name == "unic-backup" for t in threading.enumerate())


def test_scheduler_still_starts_in_normal_operation(monkeypatch):
    started = []
    monkeypatch.delenv("UNIC_NO_BACKGROUND", raising=False)

    class FakeThread:
        def __init__(self, target=None, name="", daemon=False):
            started.append(name)

        def start(self):
            pass
    monkeypatch.setattr(backup.threading, "Thread", FakeThread)
    backup.start_scheduler()
    assert started == ["unic-backup"]               # en production le fil démarre bien
