#!/usr/bin/env python3
"""Factures UniC dans une session Claude Code : même code et même numérotation que le serveur, sans l'IA.

usage : python scripts/unic_facture.py liste [--n 15]                       → derniers devis et factures
        python scripts/unic_facture.py depuis-devis UC-2026-1108-AF [--avoir] → facture (ou avoir) brouillon + PDF
Base : celle de UNIC_DATA_DIR (une sauvegarde restaurée = les vrais devis du patron). Rien n'est envoyé : brouillon seulement.
Retour au serveur : python scripts/planb_export.py, puis l'import dans l'appli.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")   # ni sauvegarde ni surveillance pendant un calcul


def _fcfa(v) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", " ")


def _client(doc) -> str:
    return (doc.customer.name if getattr(doc, "customer", None) else "") or getattr(doc, "client_label", "") or "?"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("liste", help="derniers devis et factures")
    ls.add_argument("--n", type=int, default=15)
    dv = sub.add_parser("depuis-devis", help="facture brouillon à partir d'un devis")
    dv.add_argument("numero", help="numéro du devis, ex. UC-2026-1108-AF")
    dv.add_argument("--avoir", action="store_true", help="crée un avoir (-AV) au lieu d'une facture (-F)")
    args = ap.parse_args()

    from app import main as server
    from app.database import SessionLocal
    from app.models import Artifact, Invoice, Quotation
    from app.services import invoice_from_quote
    server.startup()   # tables, grille et règles du patron (idempotent)
    with SessionLocal() as db:
        if args.cmd == "liste":
            print("DEVIS")
            for q in db.query(Quotation).order_by(Quotation.created_at.desc()).limit(args.n):
                print(f"  {q.number:24} {_client(q)[:28]:28} {_fcfa(q.total):>12} FCFA  {q.status}")
            print("FACTURES")
            for i in db.query(Invoice).order_by(Invoice.created_at.desc()).limit(args.n):
                print(f"  {i.number:24} {_client(i)[:28]:28} {_fcfa(i.total):>12} FCFA  reste {_fcfa(i.remaining)}  {i.status}")
            return
        q = db.query(Quotation).filter(Quotation.number == args.numero.strip().upper()).first()
        if q is None:
            raise SystemExit(f"Devis {args.numero} introuvable dans cette base (liste : python scripts/unic_facture.py liste).")
        if not q.prices_complete:
            raise SystemExit(f"Le devis {q.number} a des lignes sans prix : complète-le avant de facturer.")
        kind = "credit" if args.avoir else "invoice"
        inv = invoice_from_quote(db, q, kind, None)
        art = db.get(Artifact, inv.artifact_id) if getattr(inv, "artifact_id", None) else None
        print(f"{'AVOIR' if args.avoir else 'FACTURE'} brouillon {inv.number} (depuis {q.number}) : {_fcfa(inv.total)} FCFA"
              f" — PDF : {art.path if art else 'non généré'}")


if __name__ == "__main__":
    main()
