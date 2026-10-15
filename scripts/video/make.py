"""Fabrique une vidéo à partir d'un scénario : python scripts/video/make.py spec.json sortie.mp4  (Playwright + ffmpeg + Pillow requis)."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import spec as sp

PAGE_VIEW = {"vertical": {"w": 360, "h": 640, "scale": 3, "mobile": True}, "horizontal": {"w": 1280, "h": 720, "scale": 1.5, "mobile": False},
             "square": {"w": 540, "h": 540, "scale": 2, "mobile": True}}
here = Path(__file__).parent
raw, out = sys.argv[1], sys.argv[2]
cfg = sp.clean(json.load(open(raw)))
FPS = int(os.environ.get("VIDEO_FPS") or cfg["fps"])      # 60 i/s par défaut : c'est ce qui donne la fluidité
if FPS not in (24, 30, 60):
    raise SystemExit("cadence : 24, 30 ou 60")
WORKERS = max(1, min(4, os.cpu_count() or 1))
w, h = sp.FORMATS[cfg["format"]]
work = Path(tempfile.mkdtemp(prefix="unic-video-"))
try:
    segs, pages = [], []
    env = {**os.environ, "VIDEO_FPS": str(FPS)}
    for i, sc in enumerate(cfg["scenes"]):
        d = work / f"s{i}"
        if sc["type"] == "page":   # une scène « page » se filme dans l'ordre du temps ; plusieurs pages se filment en même temps
            (work / f"page{i}.json").write_text(json.dumps(sc, ensure_ascii=False))
            pages.append((i, subprocess.Popen(["node", str(here / "render.mjs"), str(work / f"page{i}.json"), str(d / "f"), json.dumps(PAGE_VIEW[cfg["format"]])], env=env)))
            segs.append({"kind": "page", "fdir": str(d / "f"), "out": str(d / "o"), "frames": 0, "labels": []})
        else:
            segs.append({"kind": "html", "out": str(d), "frames": round(sc["seconds"] * FPS), "scene": sc})
    def run_scenes(only: str, n: int):
        procs = [subprocess.Popen(["node", str(here / "scenes.mjs"), str(work / "plan.json")], env={**env, "ONLY": only, "WORKER": str(k), "WORKERS": str(n)}) for k in range(n)]
        if any([p.wait() for p in procs]):
            raise SystemExit("le rendu des scènes a échoué")
    # les scènes HTML ne dépendent pas des pages : on les rend pendant que les pages se filment (cœurs libres)
    (work / "plan.json").write_text(json.dumps({"view": {"w": w, "h": h}, "fps": FPS, "segments": segs}, ensure_ascii=False))
    run_scenes("html", max(1, WORKERS - 1) if pages else WORKERS)
    for i, proc in pages:
        if proc.wait():
            raise SystemExit(f"la capture de la scène {i + 1} a échoué")
        m = json.load(open(work / f"s{i}" / "f" / "meta.json"))
        segs[i].update(frames=m["frames"], labels=m["labels"])
    (work / "plan.json").write_text(json.dumps({"view": {"w": w, "h": h}, "fps": FPS, "segments": segs}, ensure_ascii=False))   # durées et chapitres des pages connus
    if pages:
        run_scenes("pill", WORKERS)
    for s in segs:   # fusion des listes de pastilles écrites par chaque Chrome
        if s["kind"] == "page":
            done = sorted(sum((json.load(open(f)) for f in Path(s["out"]).glob("list.*.json")), []))
            Path(s["out"], "list.json").write_text(json.dumps(done))
    subprocess.run([sys.executable, str(here / "compose.py"), str(work / "plan.json"), out], check=True, env=env)
finally:
    shutil.rmtree(work, ignore_errors=True)
