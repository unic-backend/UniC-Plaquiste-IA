"""Devis et factures écrits comme un professionnel : désignation propre (le conditionnement va dans « Unité », jamais de prix
dans la désignation), devise une seule fois dans l'en-tête, montant arrêté en toutes lettres."""
import pypdfium2 as pdfium

from app import pdfs


def test_designation_propre_et_unite_dans_sa_colonne():
    t = pdfs.tidy_item
    assert t("Tiges 1 m (paquet de 100 tiges à 300 FCFA)", "paquet") == ("Tige 1 m", "Paquet de 100")
    assert t("Éclipses pour IPN (paquet de 100)", "paquet") == ("Éclipse pour IPN", "Paquet de 100")
    assert t("Paquet vis 25 mm", "paquet") == ("Vis 25 mm", "Paquet")
    assert t("Paquet chevilles à frapper", "paquet") == ("Cheville à frapper", "Paquet")
    assert t("Barre de fourrure (2,80 m)", "barre") == ("Fourrure 2,80 m", "Barre")
    assert t("Cornières", "barre") == ("Cornière", "Barre")
    assert t("Sac enduit", "sac") == ("Enduit", "Sac")
    assert t("Plaque de plâtre BA13 2000×1200", "u") == ("Plaque de plâtre BA13 2000×1200", "Unité")
    assert t("Livraison : à la charge du client", "forfait") == ("Livraison : à la charge du client", "Forfait")   # libellé du patron gardé
    assert t("Main-d'œuvre — pose complète", "m²") == ("Main-d'œuvre — pose complète", "m²")
    assert t("Frais de transport", "forfait")[0] == "Frais de transport"                                          # « Frais » n'est pas un pluriel à couper


def test_montant_en_lettres_orthographe_traditionnelle():
    L = pdfs.en_lettres
    assert L(2_791_000) == "deux millions sept cent quatre-vingt-onze mille"
    assert L(1_050_500) == "un million cinquante mille cinq cents"
    assert (L(80), L(81), L(80_000), L(180)) == ("quatre-vingts", "quatre-vingt-un", "quatre-vingt mille", "cent quatre-vingts")
    assert (L(200), L(201), L(200_000), L(1000)) == ("deux cents", "deux cent un", "deux cent mille", "mille")
    assert (L(21), L(71), L(91), L(0)) == ("vingt et un", "soixante et onze", "quatre-vingt-onze", "zéro")


def test_devis_pdf_professionnel(tmp_path):
    rows = [["1", "Tiges 1 m (paquet de 100 tiges à 300 FCFA)", "5,00", "paquet", "30 000 FCFA", "150 000 FCFA"],
            ["2", "Livraison : à la charge du client", "1,00", "forfait", "0 FCFA", "0 FCFA"]]
    out = pdfs.build_document_pdf(tmp_path / "d.pdf", company={"name": "UniC Plaquiste"}, doc_label="DEVIS", number="UC-T", title="Faux plafond",
                                  status="draft", meta_lines=["N° UC-T", "Date 04/11/2026", "Statut brouillon"], party_left=("É", "x"),
                                  party_right=("Client", "Oumar\nLieu du chantier : Colobane"),
                                  headers=["#", "Désignation", "Qté", "Unité", "P.U.", "Total"], rows=rows, col_widths=[1] * 6,
                                  totals=[("Sous-total HT", "150 000 FCFA"), ("Total", "150 000 FCFA")])
    text = " ".join("".join(p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(out))).split())   # retours à la ligne du PDF ignorés
    assert "Tige 1 m" in text and "Paquet de 100" in text and "300 FCFA" not in text and "à 300" not in text
    assert "P.U. (FCFA)" in text and "Montant (FCFA)" in text and "30 000" in text
    assert "Arrêté le présent devis à la somme de" in text and "Cent cinquante mille francs CFA" in text
    assert text.count("150 000 FCFA") == 2 and "Sous-total HT" not in text          # le total une fois (et en lettres), pas de doublon HT = total
    assert "brouillon" not in text.lower() and "Bon pour accord" in text
