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


def test_exemples_de_la_competence_egaux_au_moteur(tmp_path):
    """EXEMPLES.md sert de référence au chat : ses totaux doivent sortir du moteur, sinon le chat apprend de faux chiffres."""
    import os
    import re
    import subprocess
    import sys
    ex = (ROOT / "docs/skills/unic-devis/EXEMPLES.md").read_text(encoding="utf-8")
    cas = {"199 700": '[{"name":"Salon","kind":"ceiling","length_m":5,"width_m":4,"support":"dalle"}]',
           "156 100": '[{"name":"Chambre","kind":"ceiling","length_m":4,"width_m":3.5,"support":"dalle"}]',
           "532 800": '[{"name":"Bureau","kind":"ceiling","length_m":8,"width_m":7,"support":"ipn","suspente_m":1.5}]',
           "167 800": '[{"name":"Mur","kind":"partition","length_m":6,"height_m":2.5,"sides":2,"doors":1}]'}
    env = {**os.environ, "UNIC_DATA_DIR": str(tmp_path)}
    for total, pieces in cas.items():
        assert total in ex
        r = subprocess.run([sys.executable, str(ROOT / "scripts/unic_calcul.py"), pieces, "--main-oeuvre", "3000"],
                           capture_output=True, text=True, timeout=120, env=env)
        assert re.search(r"TOTAL : " + total + " FCFA", r.stdout), (total, r.stdout[-400:])
