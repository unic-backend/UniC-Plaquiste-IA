#!/usr/bin/env python3
"""Moteur de calcul d'UniC dans une session Claude Code : même code, mêmes règles du patron, mêmes prix que le serveur, sans l'IA.

usage : python scripts/unic_calcul.py '<pièces en JSON>' [--main-oeuvre PRIX_M2] [--json]
        python scripts/unic_calcul.py pieces.json ...
        python scripts/unic_calcul.py pieces.json --devis "Nom du client" [--lieu Médina] [--objet "..."]  → devis brouillon + PDF
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
    ap.add_argument("--devis", metavar="CLIENT", help="crée aussi le devis brouillon (numéro, PDF) au nom de ce client")
    ap.add_argument("--lieu", default="", help="lieu du chantier (avec --devis)")
    ap.add_argument("--objet", default="", help="objet du devis (avec --devis ; sinon objet automatique)")
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
            if args.devis:   # même création que l'appli : numéro, grille, PDF ; refusé si le contrôle du calcul trouve un écart
                from app.models import Artifact
                q = pieces.create_quote(db, None, rooms, client=args.devis, lieu=args.lieu, objet=args.objet, labour_m2=args.main_oeuvre)
                art = db.get(Artifact, q.artifact_id) if q.artifact_id else None
                out["devis"] = {"numero": q.number, "total": q.total, "complet": q.prices_complete, "pdf": art.path if art else None}
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
    if out.get("devis"):
        d = out["devis"]
        print(f"DEVIS brouillon {d['numero']} : {_fcfa(d['total'])} FCFA{'' if d['complet'] else ' (prix incomplets)'} — PDF : {d['pdf']}")


if __name__ == "__main__":
    main()
