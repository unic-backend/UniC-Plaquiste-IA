"""Vision : une capture allongée (devis sur téléphone) est lue par tranches ; une image normale reste entière."""
from PIL import Image

from app import vision


def test_image_normale_inchangee():
    img = Image.new("RGB", (1200, 900), "white")
    assert vision.tiles(img) == [img]


def test_capture_allongee_en_tranches_qui_se_recouvrent():
    img = Image.new("RGB", (1080, 2400), "white")
    parts = vision.tiles(img)
    assert 2 <= len(parts) <= vision.MAX_TILES
    assert all(p.size[0] == 1080 for p in parts)
    assert sum(p.size[1] for p in parts) > 2400          # recouvrement : rien n'est perdu
    assert all(p.size[1] / p.size[0] <= vision.TILE_RATIO + 0.5 for p in parts)


def test_tres_longue_image_bornee():
    assert len(vision.tiles(Image.new("RGB", (500, 9000), "white"))) == vision.MAX_TILES


def test_describe_image_assemble_les_parties(tmp_path, monkeypatch):
    p = tmp_path / "devis.png"
    Image.new("RGB", (1080, 2400), "white").save(p)
    monkeypatch.setattr(vision, "disponible", lambda: True)
    calls = []
    monkeypatch.setattr(vision, "_ask", lambda b64: calls.append(1) or f"texte {len(calls)}")
    out = vision.describe_image(p)
    assert len(calls) >= 2 and "[Partie 1/" in out and "texte 2" in out
