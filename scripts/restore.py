#!/usr/bin/env python3
"""Restauration d'une sauvegarde UniC AI. À tester avant de faire confiance à un backup."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402


def main(src: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Sauvegarde introuvable : {src}")
    settings.data_path.mkdir(parents=True, exist_ok=True)
    db = src / "unic.db"
    if db.exists():
        shutil.copy2(db, settings.data_path / "unic.db")
    st = src / "storage"
    if st.exists():
        target = settings.storage_path
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(st, target)
    print("Restauration terminée. Redémarrez UniC AI et vérifiez un devis PDF + un login.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/restore.py <dossier-sauvegarde>")
    main(Path(sys.argv[1]))
