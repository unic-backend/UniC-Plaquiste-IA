"""La compétence unic-devis embarque les prix pour Claude chat : la copie doit suivre la mémoire (sinon prix périmés)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_prix_de_la_competence_suivent_la_memoire():
    spec = importlib.util.spec_from_file_location("skill_prix", ROOT / "scripts" / "skill_prix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    copie = (ROOT / "docs/skills/unic-devis/PRIX-ET-REGLES.md").read_text(encoding="utf-8")
    assert copie == mod.contenu(), "Prix changés : lance python scripts/skill_prix.py puis réimporte le zip unic-devis"
    assert "1 200" in copie and "Main-d'œuvre" in copie
