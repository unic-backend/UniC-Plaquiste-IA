"""Fichiers de l'interface : cache long seulement pour ceux dont le nom porte l'empreinte du contenu."""
import os
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import HashedAssets  # noqa: E402


def test_only_content_hashed_files_get_the_one_year_cache(tmp_path):
    for name in ("Atelier-Dz18C-go.js", "index-C_ZvWsQl.css", "pdf.worker.min-rsCePomN.mjs", "favicon.svg", "index.js", "court-abc.js"):
        (tmp_path / name).write_text("x")
    mini = FastAPI()
    mini.mount("/assets", HashedAssets(directory=tmp_path), name="assets")
    c = TestClient(mini)
    for hashed in ("Atelier-Dz18C-go.js", "index-C_ZvWsQl.css", "pdf.worker.min-rsCePomN.mjs"):
        r = c.get(f"/assets/{hashed}")
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable", hashed
    for plain in ("favicon.svg", "index.js", "court-abc.js"):                   # sans empreinte : jamais de cache long
        r = c.get(f"/assets/{plain}")
        assert r.status_code == 200 and "immutable" not in r.headers.get("cache-control", ""), plain
    assert "immutable" not in c.get("/assets/inexistant-12345678.js").headers.get("cache-control", "")   # 404 : jamais gardé
