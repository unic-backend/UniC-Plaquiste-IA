"""Modèles HyperFrames (scripts/video/modeles) : chaque modèle se rend seul, hors ligne, et pareil à chaque fois."""
import pathlib
import re

import pytest

MODELES = sorted((pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video" / "modeles").glob("*/index.html"))
EXTERNE = re.compile(r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|from\s+["']https?://""")


def test_les_modeles_sont_trouves():
    assert {p.parent.name for p in MODELES} >= {"cloison", "plafond", "devis", "references", "etapes", "points", "bonhomme", "trajet", "etsi", "enquete", "produit"}


@pytest.mark.parametrize("page", MODELES, ids=lambda p: p.parent.name)
def test_modele_complet_hors_ligne_et_deterministe(page):
    html = page.read_text(encoding="utf-8")
    assert 'data-composition-id="main"' in html and re.search(r'data-duration="\d+(\.\d+)?"', html)
    assert 'window.__timelines["main"]' in html
    assert not EXTERNE.search(html), "bibliothèques, polices et images en local (lib/, fonts/, assets/), jamais depuis Internet"
    # HyperFrames filme les images dans le désordre : rien ne doit dépendre de l'horloge ni du hasard
    assert not re.search(r"Math\.random|Date\.now|performance\.now|new Date\(", html)
    # GSAP arrondit les px : un tracé (pathLength=1) animé en style saute de 1 à 0 au lieu de se dessiner
    assert "strokeDashoffset" not in html, 'animer attr: { "stroke-dashoffset": … }'
