#!/usr/bin/env python3
"""Taux de change réels dans une session Claude Code : même module que UniC IA (backend/app/change.py), sans base ni IA.

usage : python scripts/unic_change.py 1500 USD            → en FCFA
        python scripts/unic_change.py 2000000 FCFA EUR     → de FCFA vers euro
        python scripts/unic_change.py 980 yuan --json
FCFA ↔ euro : parité fixe 655,957 (sans réseau). Autres monnaies : taux de référence BCE du jour (Frankfurter).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("montant")
    ap.add_argument("de", help="monnaie de départ (USD, EUR, CNY, GBP, FCFA, dollar, yuan…)")
    ap.add_argument("vers", nargs="?", default="FCFA", help="monnaie d'arrivée (FCFA par défaut)")
    ap.add_argument("--json", action="store_true", help="résultat complet en JSON")
    args = ap.parse_args()

    from app import change
    out = change.convertir(args.montant, args.de, args.vers)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if "error" in out:
        raise SystemExit(out["error"])
    res = f"{out['resultat']:,.0f}" if out["vers"] == "XOF" else f"{out['resultat']:,.2f}"
    print(f"{out['montant']:,g} {out['de']} = {res} {out['vers']}".replace(",", " "))
    print(f"{out['taux']} — {out['date_du_taux']} — {out['source']}")
    if out.get("note"):
        print(out["note"])


if __name__ == "__main__":
    main()
