"""Fabrique une vidéo à partir d'un scénario : python scripts/video/make.py spec.json sortie.mp4  (Playwright + ffmpeg + Pillow requis)."""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import spec as sp

PAGE_VIEW = {"vertical": {"w": 360, "h": 640, "scale": 3, "mobile": True}, "horizontal": {"w": 1280, "h": 720, "scale": 1.5, "mobile": False},
             "square": {"w": 540, "h": 540, "scale": 2, "mobile": True}}
here = Path(__file__).parent
raw, out = sys.argv[1], sys.argv[2]
cfg = sp.clean(json.load(open(raw)))
w, h = sp.FORMATS[cfg["format"]]
work = Path(tempfile.mkdtemp(prefix="unic-video-"))
try:
    segs = []
    for i, sc in enumerate(cfg["scenes"]):
        d = work / f"s{i}"
        if sc["type"] == "page":
            (work / f"page{i}.json").write_text(json.dumps(sc, ensure_ascii=False))
            subprocess.run(["node", str(here / "render.mjs"), str(work / f"page{i}.json"), str(d / "f"), json.dumps(PAGE_VIEW[cfg["format"]])], check=True)
            m = json.load(open(d / "f" / "meta.json"))
            segs.append({"kind": "page", "fdir": str(d / "f"), "out": str(d / "o"), "frames": m["frames"], "labels": m["labels"]})
        else:
            segs.append({"kind": "html", "out": str(d), "frames": round(sc["seconds"] * 60), "scene": sc})
    (work / "plan.json").write_text(json.dumps({"view": {"w": w, "h": h}, "segments": segs}, ensure_ascii=False))
    subprocess.run(["node", str(here / "scenes.mjs"), str(work / "plan.json")], check=True)
    subprocess.run([sys.executable, str(here / "compose.py"), str(work / "plan.json"), out], check=True)
finally:
    shutil.rmtree(work, ignore_errors=True)
