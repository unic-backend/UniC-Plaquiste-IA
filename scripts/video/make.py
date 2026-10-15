"""Fabrique une vidéo à partir d'un scénario : python scripts/video/make.py spec.json sortie.mp4  (Playwright + ffmpeg + Pillow requis)."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import spec as sp

here = Path(__file__).parent
raw, out = sys.argv[1], sys.argv[2]
cfg = sp.clean(json.load(open(raw)))
work = Path(tempfile.mkdtemp(prefix="unic-video-"))
try:
    (work / "spec.json").write_text(json.dumps(cfg, ensure_ascii=False))
    run = lambda *a: subprocess.run(list(a), check=True)
    run("node", str(here / "render.mjs"), str(work / "spec.json"), str(work / "f"))
    run("node", str(here / "overlay.mjs"), str(work / "spec.json"), str(work / "f"), str(work / "o"))
    run(sys.executable, str(here / "compose.py"), str(work / "f"), str(work / "o"), out)
finally:
    shutil.rmtree(work, ignore_errors=True)
