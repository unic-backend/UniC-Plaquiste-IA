"""Mots du métier mal écrits ou dictés de travers, compris comme le patron les pense (moulure, hydrofuge, caisson, ratissage,
fenêtre, cornière…). Les mots justes ne changent jamais."""
import pytest

from app import calc


@pytest.mark.parametrize("text, kind, needle", [
    ("moulur salon 5x4", "moulure", "18 ml"),
    ("mouleur 18 ml", "moulure", "18 ml"),
    ("faux plafond sdb 3x2 hidrofuge", "ceiling", "hydrofuges"),
    ("faux plafond 5x4 avec caison", "ceiling", "caisson"),
    ("ratisage 30 m2", "plaster", "2 mm"),
    ("cloison 4x2,5 avec fenetre 120x100", "partition", "1 ouverture"),
])
def test_mots_du_metier_mal_ecrits(text, kind, needle):
    r = calc.calculate_from_text(text)
    assert r.kind == kind and needle in r.understanding


@pytest.mark.parametrize("raw, fixed", [
    ("osature et cornier", "ossature et cornière"),
    ("tije et chevile", "tige et cheville"),
    ("le metrage de la plak", "le métré de la plaque"),
    ("la cornière est posée", "la cornière est posée"),        # mot juste : inchangé
])
def test_fautes_corrigees_mots_justes_gardes(raw, fixed):
    assert calc.fix_typos(raw) == fixed
