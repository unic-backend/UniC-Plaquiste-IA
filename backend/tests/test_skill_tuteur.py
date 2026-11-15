"""Tuteur UniC (docs/skills/unic-tuteur) : il n'enseigne que les règles écrites du patron et le cas de référence du moteur."""
import pathlib

DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs"
TUTEUR = (DOCS / "skills" / "unic-tuteur" / "SKILL.md").read_text(encoding="utf-8")
MEMOIRE = (DOCS / "MEMOIRE-CLAUDE.md").read_text(encoding="utf-8")
EXEMPLES = (DOCS / "skills" / "unic-devis" / "EXEMPLES.md").read_text(encoding="utf-8")


def test_les_regles_du_tuteur_sont_celles_de_la_memoire():
    # chaque règle chiffrée de la Banque existe telle quelle dans la mémoire du patron : une règle changée là-bas casse ce test
    for regle in ("2 m × 1,20 m", "2,80 m", "fourrures tous les 0,50 m", "la première à 0,30 m du mur puis une tous les 0,90 m",
                  "une tous les 30 cm de cornière ou de rail", "un montant tous les 0,60 m (0,50 si plaque couchée)",
                  "3 montants de renfort par porte", "raccord de rail de 40 cm", "vis à plaque 15/m²", "bande 1,40 ml/m²",
                  "rouleau de 150 m", "enduit 0,35 kg/m² par couche (2 couches)", "sac de 20 kg", "4 vis de 9 mm par montant",
                  "lames de 3 m, toujours dans le sens de la largeur", "jamais rouge (phase) sur bleu (neutre)"):
        assert regle in MEMOIRE, regle
    for ici in ("0,30 m du mur, puis une tous les 0,90 m", "un tous les 0,60 m (0,50 si plaque couchée)", "15 par m²", "1,40 ml par m²",
                "0,35 kg par m² et par couche", "+ 3 pièces sous 50 m²", "+ 10 au-delà de 100 m²"):
        assert ici in TUTEUR, ici


def test_le_cas_de_reference_est_celui_du_moteur():
    for chiffre in ("**9 lignes**", "**54 tiges**", "**20**", "**10**"):
        assert chiffre in EXEMPLES, chiffre
    for chiffre in ("**9 lignes**", "**54 tiges**", "**20 fourrures**", "**12 plaques**", "**10 cornières**"):
        assert chiffre in TUTEUR, chiffre
    assert "Plaque BA13 2000×1200 | 12 |" in EXEMPLES   # 12 plaques dans le tableau du moteur


def test_le_tuteur_garde_les_garde_fous():
    for garde in ("Une seule question à la fois", "jamais la solution avant une tentative", "à confirmer", "Aucun nom de client", "jamais un calcul de devis"):
        assert garde in TUTEUR, garde
