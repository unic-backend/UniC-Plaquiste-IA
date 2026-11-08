#!/usr/bin/env python3
"""Dossier Claude Code → serveur : exporte les devis, factures et clients créés depuis la sauvegarde restaurée dans cette base locale.

usage : python scripts/planb_export.py [--depuis AAAA-MM-JJ[THH:MM]] [--sortie fichier.json]
Sans --depuis : la date de la sauvegarde restaurée (backup.restore la note). Le fichier s'importe ensuite dans l'appli :
Paramètres › Moteur & santé › Sauvegardes › « Importer un dossier de Claude ». Rejouable sans doublon (voir backend/app/planb.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import backup, planb  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depuis", help="ne garder que ce qui est créé à partir de cette date (ISO)")
    ap.add_argument("--sortie", help="fichier à écrire (défaut : dossier-claude-AAAA-MM-JJ.json)")
    args = ap.parse_args()
    raw = args.depuis or backup.status().get("last_restore_from")
    since = planb._utc(raw)
    if raw and since is None:
        raise SystemExit(f"Date illisible : {raw} (format AAAA-MM-JJ ou AAAA-MM-JJTHH:MM).")
    if since is None:
        print("Aucune date de sauvegarde restaurée trouvée : TOUT est exporté (le serveur ignorera ce qu'il a déjà).", file=sys.stderr)
    with SessionLocal() as db:
        bundle = planb.export_bundle(db, since)
    out = Path(args.sortie or f"dossier-claude-{datetime.now(timezone.utc):%Y-%m-%d}.json")
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out} : {len(bundle['quotes'])} devis, {len(bundle['invoices'])} factures, {len(bundle['customers'])} clients.")


if __name__ == "__main__":
    main()
