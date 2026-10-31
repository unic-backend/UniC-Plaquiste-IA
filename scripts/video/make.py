"""Fabrique une vidéo à partir d'un scénario : python scripts/video/make.py spec.json sortie.mp4  (Playwright + ffmpeg + Pillow requis)."""
import json, os, shutil, subprocess, sys, tempfile, urllib.request
from urllib.parse import urlparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import spec as sp
import edit

PAGE_VIEW = {"vertical": {"w": 360, "h": 640, "scale": 3, "mobile": True}, "horizontal": {"w": 1280, "h": 720, "scale": 1.5, "mobile": False},
             "square": {"w": 540, "h": 540, "scale": 2, "mobile": True}}
here = Path(__file__).parent
MAX_CLIP_BYTES = 600 * 1024 * 1024


def fetch_media(url: str, dest: Path) -> None:
    """Télécharge un média généré (clip d'IA). L'adresse est déjà validée (spec.py) ; on revérifie après redirection, avec une taille maximale."""
    req = urllib.request.Request(url, headers={"User-Agent": "unic-video/1"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:   # noqa: S310
        final = urlparse(r.geturl())
        if not (final.scheme == "https" or (os.environ.get("VIDEO_ALLOW_LOCAL") == "1" and final.hostname in ("localhost", "127.0.0.1"))):
            raise SystemExit("téléchargement refusé : redirection hors https")
        size = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_CLIP_BYTES:
                raise SystemExit("clip trop volumineux")
            f.write(chunk)
args = sys.argv[1:]
raw = args[0]
cfg = sp.clean(json.load(open(raw)))
if "--plan" in args:   # plan des tronçons (GitHub Actions) : {"chunks": N, "matrix": [0..N-1], "seconds": total}
    parts = sp.chunks(cfg["scenes"], float(os.environ.get("CHUNK_SECONDS", "90")))
    print(json.dumps({"chunks": len(parts), "matrix": list(range(len(parts))), "seconds": round(sum(sp.scene_seconds(s) for s in cfg["scenes"]))}))
    raise SystemExit(0)
out = args[1]
CHUNK_OFFSET = 0.0   # début du tronçon dans la vidéo entière (pour caler musique et voix)
if "--chunk" in args:   # un seul tronçon : fondu d'entrée sur le premier, de sortie sur le dernier
    k = int(args[args.index("--chunk") + 1]); parts = sp.chunks(cfg["scenes"], float(os.environ.get("CHUNK_SECONDS", "90")))
    CHUNK_OFFSET = sum(sp.scene_seconds(s) for p in parts[:k] for s in p)
    cfg["scenes"] = parts[k]
    os.environ["FADE_IN"], os.environ["FADE_OUT"] = ("1" if k == 0 else "0"), ("1" if k == len(parts) - 1 else "0")
FPS = int(os.environ.get("VIDEO_FPS") or cfg["fps"])      # 60 i/s par défaut : c'est ce qui donne la fluidité
if FPS not in (24, 30, 60):
    raise SystemExit("cadence : 24, 30 ou 60")
WORKERS = max(1, min(4, os.cpu_count() or 1))
w, h = sp.FORMATS[cfg["format"]]
work = Path(tempfile.mkdtemp(prefix="unic-video-"))
try:
    segs, pages, clips = [], [], []
    env = {**os.environ, "VIDEO_FPS": str(FPS)}
    for i, sc in enumerate(cfg["scenes"]):
        d = work / f"s{i}"
        if sc["type"] == "page":   # une scène « page » se filme dans l'ordre du temps ; plusieurs pages se filment en même temps
            (work / f"page{i}.json").write_text(json.dumps(sc, ensure_ascii=False))
            pages.append((i, subprocess.Popen(["node", str(here / "render.mjs"), str(work / f"page{i}.json"), str(d / "f"), json.dumps(PAGE_VIEW[cfg["format"]])], env=env)))
            segs.append({"kind": "page", "fdir": str(d / "f"), "out": str(d / "o"), "frames": 0, "labels": []})
        elif sc["type"] == "clip":   # vrai film (patron ou IA) MONTÉ (edit.py) : vitesse, couleurs, cadrage, arrêt sur image, écran partagé
            src = work / f"clip{i}.mp4"
            fetch_media(sc["url"], src)
            src2 = None
            if sc.get("split"):
                src2 = work / f"clip{i}b.mp4"
                fetch_media(sc["split"]["url"], src2)
            n = round(sc["seconds"] * FPS); d.mkdir(parents=True, exist_ok=True)
            clips.append((i, subprocess.Popen(edit.ffmpeg_args(sc, src, src2, w * 3, h * 3, FPS, n, str(d / "%05d.jpg")))))
            segs.append({"kind": "clip", "out": str(d), "frames": n, **({"overlay": sc["overlay"], "ovl": str(work / f"o{i}")} if sc.get("overlay") else {}),
                         **{k: sc[k] for k in ("zoom", "zoom_amount", "focus", "transition") if k in sc}})   # zoom et transitions : image par image (compose.py)
        else:
            segs.append({"kind": "html", "out": str(d), "frames": round(sc["seconds"] * FPS), "scene": sc})
    def run_scenes(only: str, n: int):
        procs = [subprocess.Popen(["node", str(here / "scenes.mjs"), str(work / "plan.json")], env={**env, "ONLY": only, "WORKER": str(k), "WORKERS": str(n)}) for k in range(n)]
        if any([p.wait() for p in procs]):
            raise SystemExit("le rendu des scènes a échoué")
    # les scènes HTML ne dépendent pas des pages : on les rend pendant que les pages se filment (cœurs libres)
    (work / "plan.json").write_text(json.dumps({"view": {"w": w, "h": h}, "fps": FPS, "theme": cfg["theme"], "segments": segs}, ensure_ascii=False))
    run_scenes("html", max(1, WORKERS - 1) if pages else WORKERS)
    for i, proc in clips:
        if proc.wait():
            raise SystemExit(f"le clip de la scène {i + 1} n'a pas pu être mis au format (fichier vidéo invalide ?)")
        if len(list((work / f"s{i}").glob("*.jpg"))) < segs[i]["frames"]:
            raise SystemExit(f"le clip de la scène {i + 1} est vide")
    for i, proc in pages:
        if proc.wait():
            raise SystemExit(f"la capture de la scène {i + 1} a échoué")
        m = json.load(open(work / f"s{i}" / "f" / "meta.json"))
        segs[i].update(frames=m["frames"], labels=m["labels"])
    (work / "plan.json").write_text(json.dumps({"view": {"w": w, "h": h}, "fps": FPS, "theme": cfg["theme"], "segments": segs}, ensure_ascii=False))   # durées et chapitres des pages connus
    if pages:
        run_scenes("pill", WORKERS)
    for s in segs:   # fusion des listes de pastilles écrites par chaque Chrome
        if s["kind"] == "page":
            done = sorted(sum((json.load(open(f)) for f in Path(s["out"]).glob("list.*.json")), []))
            Path(s["out"], "list.json").write_text(json.dumps(done))
    au = cfg.get("audio")
    silent = out if not au else str(work / "silent.mp4")
    subprocess.run([sys.executable, str(here / "compose.py"), str(work / "plan.json"), silent], check=True, env=env)
    if au:   # bande son du tronçon : musique, voix, clavier (sound.py), puis réunion image + son sans ré-encoder l'image
        import sound
        files = {}
        for key in ("music", "voice"):
            if au.get(key):
                files[key] = work / f"{key}.audio"
                fetch_media(au[key]["url"], files[key])
        timeline, t = [], 0.0
        for sc, sg in zip(cfg["scenes"], segs):
            secs = sg["frames"] / FPS
            timeline.append((t, secs, sc)); t += secs
        wav = sound.build(au, timeline, files, CHUNK_OFFSET, t, work, os.environ.get("FADE_IN", "1") == "1", os.environ.get("FADE_OUT", "1") == "1")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", "-movflags", "+faststart", out], check=True)
finally:
    shutil.rmtree(work, ignore_errors=True)
