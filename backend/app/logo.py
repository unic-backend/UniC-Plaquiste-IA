"""Création de logos : guides de conception (dépôt MIT logo-design-skill) + audit technique d'un SVG.

Les guides sont lus à la demande par l'IA (outil `logo_guide`) ; l'audit tourne dans un sous-processus isolé.
La bibliothèque de 1 432 logos de marques tierces n'est pas reprise (marques déposées, non redistribuables).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app import diagrams

BASE = Path(__file__).parent / "skills" / "logo_design"
TOPICS = {
    "processus": "process.md", "brief": "discovery-brief.md", "principes": "principles.md", "types_de_marques": "mark-types.md",
    "construction_svg": "svg-construction.md", "techniques_visuelles": "visual-techniques.md", "couleur": "color.md",
    "typographie": "typography.md", "tests": "testing-checklist.md", "critique": "critique.md", "refonte": "redesign.md",
    "systeme_identite": "identity-system.md", "presentation": "presentation-delivery.md",
}
MAX_CHARS = 14000
NOTE = ("(Guide anglais, source MIT. Ignore les scripts et la bibliothèque de logos cités : ils ne sont pas installés. "
        "Outils réels : logo_guide, draw_diagram, audit_logo. Réponds toujours en français.)\n\n")


def guide(topic: str) -> dict:
    name = TOPICS.get((topic or "").strip().lower())
    if not name:
        return {"error": "Sujet inconnu.", "sujets": sorted(TOPICS)}
    text = (BASE / "references" / name).read_text(encoding="utf-8")
    return {"sujet": topic, "texte": NOTE + text[:MAX_CHARS], "tronque": len(text) > MAX_CHARS}


def audit(svg: str) -> dict:
    """Rapport d'audit d'un SVG de logo (structure, couleurs, texte vivant, détails trop fins…)."""
    safe = diagrams.sanitize(svg)   # même nettoyage que pour les dessins
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "logo.svg"
        f.write_text(safe, encoding="utf-8")
        try:
            run = subprocess.run([sys.executable, str(BASE / "scripts" / "svg_audit.py"), "--json", str(f)],
                                 capture_output=True, text=True, timeout=30, cwd=tmp)
            data = json.loads(run.stdout)[0]
        except Exception as exc:
            raise diagrams.DiagramError("Audit impossible.") from exc
    if "error" in data:
        raise diagrams.DiagramError("Audit impossible : SVG non lisible.")
    return {"score": data.get("score"), "couleurs": data.get("colors"), "ancres": data.get("anchors"),
            "constats": [f"{x['level']} {x['message']}" for x in data.get("findings", [])][:15]}
