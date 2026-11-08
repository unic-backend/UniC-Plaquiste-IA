#!/usr/bin/env python3
"""Moteur de calcul d'UniC dans une session Claude Code : même code, mêmes règles du patron, mêmes prix que le serveur, sans l'IA.

usage : python scripts/unic_calcul.py '<pièces en JSON>' [--main-oeuvre PRIX_M2] [--json]
        python scripts/unic_calcul.py pieces.json ...
Pièce : {"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4, "support": "dalle"|"ipn", "suspente_m": 3}
        {"name": "Mur", "kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2, "doors": 1}
        {"name": "Murs", "kind": "paint", "area_m2": 40, "coats": 2}
Base : celle de UNIC_DATA_DIR (une sauvegarde restaurée = les prix du patron) ; base neuve = grille du dépôt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")   # un calcul ne lance ni sauvegarde ni surveillance


def _fcfa(v) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", " ")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pieces", help="liste de pièces en JSON, ou chemin d'un fichier .json")
    ap.add_argument("--main-oeuvre", type=float, help="prix de pose au m² donné par le patron")
    ap.add_argument("--json", action="store_true", help="résultat complet en JSON")
    args = ap.parse_args()
    raw = Path(args.pieces).read_text(encoding="utf-8") if args.pieces.endswith(".json") else args.pieces
    try:
        rooms = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON illisible : {exc}") from None
    rooms = [rooms] if isinstance(rooms, dict) else rooms

    from app import main as server, pieces
    from app.database import SessionLocal
    server.startup()   # tables, grille et règles du patron (idempotent)
    with SessionLocal() as db:
        try:
            out = pieces.calculate(db, rooms, labour_m2=args.main_oeuvre)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for b in out["blocs"]:
        print(f"{b['type']} — {b['pieces']} : {b['surface_m2']} m²" + ("" if b["verification"].get("ok", True) else "  ⚠ vérification KO"))
    print()
    for line in out["lignes"]:
        print(f"{line['name'][:44]:44} {line['quantity']:>8g} {line['unit']:<7} × {_fcfa(line['prix_unitaire']):>8} = {_fcfa(line['montant']):>10}")
    if out["main_oeuvre"]:
        mo = out["main_oeuvre"]
        print(f"{mo['name'][:44]:44} {mo['quantity']:>8g} m²      × {_fcfa(mo['prix_unitaire']):>8} = {_fcfa(mo['montant']):>10}")
    print(f"\nTOTAL : {_fcfa(out['total'])} FCFA" + (f"  (prix manquants : {', '.join(out['prix_manquants'])})" if out["prix_manquants"] else ""))


if __name__ == "__main__":
    main()
