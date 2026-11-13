"""Étude d'une vidéo de référence (scripts/video/etudier.py) : une image tous les quarts de seconde, en planches lisibles."""
import importlib.util
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "video"
_spec = importlib.util.spec_from_file_location("video_etudier", ROOT / "etudier.py")
etu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(etu)


def test_la_planche_suit_le_format_de_la_video():
    assert etu.grille(1080, 1920) == (7, 2, 270)     # vertical : 14 images côte à côte
    assert etu.grille(1920, 1080) == (4, 4, 480)
    assert etu.grille(1080, 1080) == (5, 3, 380)
    assert etu.filtre(1080, 1920) == "fps=4,scale=270:-2,tile=7x2:padding=4:margin=4"   # un quart de seconde par défaut


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_une_image_par_quart_de_seconde(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=8:size=320x180:rate=30", str(video)], check=True)
    assert etu.main(str(video), str(tmp_path / "planches")) == 2     # 8 s × 4 images = 32 images = 2 planches de 16
    with pytest.raises(SystemExit):
        etu.main(str(video), str(tmp_path / "x"), 0)
