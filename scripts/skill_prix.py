#!/usr/bin/env python3
"""Copie prix + règles de docs/MEMOIRE-CLAUDE.md dans la compétence unic-devis (Claude chat n'a pas le dépôt).

usage : python scripts/skill_prix.py          → écrit docs/skills/unic-devis/PRIX-ET-REGLES.md
Un test vérifie que la copie suit la mémoire : après un changement de prix, relance ce script et réimporte le zip.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBUT, FIN = "## Prix de vente en vigueur", "## Savoir appris par UniC"


def contenu() -> str:
    m = (ROOT / "docs/MEMOIRE-CLAUDE.md").read_text(encoding="utf-8")
    bloc = m[m.index(DEBUT):m.index(FIN)].rstrip()
    return ("# Prix et règles UniC (copie de docs/MEMOIRE-CLAUDE.md, ne pas modifier à la main)\n\n"
            "Généré par `scripts/skill_prix.py`. Ce sont les SEULS prix permis : un article absent = « prix à donner par le patron ».\n\n"
            + bloc + "\n")


if __name__ == "__main__":
    (ROOT / "docs/skills/unic-devis/PRIX-ET-REGLES.md").write_text(contenu(), encoding="utf-8")
