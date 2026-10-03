#!/usr/bin/env python3
"""Sauvegarde base + fichiers. Une sauvegarde n'est valide qu'après test de restauration."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402


def main() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = settings.backups_path / f"unic-backup-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    data = settings.data_path
    if (data / "unic.db").exists():
        shutil.copy2(data / "unic.db", dest / "unic.db")
    storage = settings.storage_path
    if storage.exists():
        shutil.copytree(storage, dest / "storage", dirs_exist_ok=True)
    (dest / "README.txt").write_text(
        "Sauvegarde UniC AI\n"
        f"date: {stamp}\n"
        "Restauration : python scripts/restore.py <ce dossier>\n"
        "Validez la restauration avant de considérer cette sauvegarde comme bonne.\n",
        encoding="utf-8",
    )
    print(dest)
    return dest


if __name__ == "__main__":
    main()
