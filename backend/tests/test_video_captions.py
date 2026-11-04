"""Sous-titres « reels » (scripts/video/captions.py) : groupes de 3 mots en majuscules, le mot prononcé en jaune, au temps exact."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video"
_spec = importlib.util.spec_from_file_location("video_captions", ROOT / "captions.py")
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

MOTS = [{"w": "Je", "s": 0.0, "e": 0.12}, {"w": "sais", "s": 0.14, "e": 0.26}, {"w": "pas", "s": 0.28, "e": 0.38},
        {"w": "si", "s": 0.40, "e": 0.52}, {"w": "vous", "s": 1.50, "e": 1.64}, {"w": "savez", "s": 1.68, "e": 1.90}]


def test_groupes_de_trois_mots_coupes_aux_silences():
    g = cap.groups(MOTS)
    assert [[m["w"] for m in x] for x in g] == [["Je", "sais", "pas"], ["si"], ["vous", "savez"]]   # 0,98 s de silence avant « vous »


def test_un_evenement_par_mot_le_mot_dit_en_jaune():
    lignes = [x for x in cap.ass(MOTS, 576, 1024).splitlines() if x.startswith("Dialogue")]
    assert len(lignes) == len(MOTS)
    premier = lignes[0]
    assert premier.startswith("Dialogue: 0,0:00:00.00,0:00:00.14,Reel,")   # jusqu'au mot suivant
    assert f"{{\\c{cap.JAUNE}}}JE" in premier and f"{{\\c{cap.BLANC}}}SAIS" in premier and f"{{\\c{cap.BLANC}}}PAS" in premier
    dernier = lignes[-1]
    assert f"{{\\c{cap.JAUNE}}}SAVEZ" in dernier and dernier.split(",")[2] == "0:00:02.05"   # fin du mot + 0,15 s


def test_taille_de_l_image_et_temps():
    texte = cap.ass(MOTS, 576, 1024)
    assert "PlayResX: 576" in texte and "PlayResY: 1024" in texte
    assert cap.t(3725.5) == "1:02:05.50"
