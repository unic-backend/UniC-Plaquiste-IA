"""Montage final : met bout à bout les scènes (page filmée avec caméra sous-pixel + pastilles, ou scènes HTML) -> MP4 60 i/s par défaut, sans mélange d'images (texte net). Sortie ≈ 24 Mo au plus."""
import json, os, subprocess, sys
from multiprocessing import Pool
from PIL import Image

PLAN, OUT = sys.argv[1:3]
P = json.load(open(PLAN)); OW, OH = P["view"]["w"] * 3, P["view"]["h"] * 3
FPS = int(P.get("fps", 60))
if FPS not in (24, 30, 60): sys.exit("fps invalide")
MARGIN, ROYAL = 1.008, (2, 8, 58)
SEGS = P["segments"]
for s in SEGS:
    if s["kind"] == "page":
        s["m"] = json.load(open(s["fdir"] + "/meta.json")); s["act"] = set(json.load(open(s["out"] + "/list.json")))   # list.json : fusion des listes des Chrome (make.py)
TASKS = [(i, f) for i, s in enumerate(SEGS) for f in range(s["frames"])]

def render(task):
    i, f = task; s = SEGS[i]
    if s["kind"] == "html":
        return Image.open(f"{s['out']}/{f:05d}.jpg").convert("RGB").tobytes()
    if s["kind"] == "clip":   # film déjà mis au format (make.py) : texte incrusté éventuel, puis le fondu aux raccords
        im = Image.open(f"{s['out']}/{f:05d}.jpg").convert("RGB")
        if s.get("overlay") and os.path.exists(f"{s['ovl']}/{f:05d}.png"):
            im = im.convert("RGBA"); im.alpha_composite(Image.open(f"{s['ovl']}/{f:05d}.png").convert("RGBA").resize((OW, OH))); im = im.convert("RGB")
        fade_frames = max(1, round(0.35 * FPS)); k = min(1.0, f / fade_frames, (s["frames"] - 1 - f) / fade_frames)
        if k < 1.0:
            im = Image.blend(Image.new("RGB", (OW, OH), ROYAL), im, max(0.0, k))
        return im.tobytes()
    m = s["m"]; W, H, S = m["W"], m["H"], m["SCALE"]
    r, z = m["meta"][min(f, m["frames"] - 1)]
    z = max(1.0, z) * MARGIN; cw, ch = W / z, H / z
    x0, y0 = (W - cw) / 2, min(max((H - ch) / 2 + r, 0), H - ch)
    im = Image.open(f"{s['fdir']}/{f:05d}.jpg").convert("RGB").resize((OW, OH), Image.LANCZOS, box=(x0 * S, y0 * S, (x0 + cw) * S, (y0 + ch) * S))
    if f in s["act"]:
        im = im.convert("RGBA"); im.alpha_composite(Image.open(f"{s['out']}/{f:05d}.png").convert("RGBA")); im = im.convert("RGB")
    fade_frames = max(1, round(0.35 * FPS))
    k = min(1.0, f / fade_frames, (s["frames"] - 1 - f) / fade_frames)     # fondu vers la couleur de fond (0,35 s) aux raccords
    if k < 1.0:
        im = Image.blend(Image.new("RGB", (OW, OH), ROYAL), im, max(0.0, k))
    return im.tobytes()

total = len(TASKS) / FPS
kbps = 4500                                   # débit plafonné, identique pour tous les tronçons (la taille croît avec la durée : pas de plafond de durée)
FADE = ("fade=t=in:st=0:d=0.4," if os.environ.get("FADE_IN", "1") == "1" else "") + (("fade=t=out:st=%.2f:d=0.8," % max(0, total - 0.8)) if os.environ.get("FADE_OUT", "1") == "1" else "")
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-framerate", str(FPS), "-i", "-",
    "-vf", "eq=contrast=1.02:saturation=1.05," + FADE + "format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
    "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-profile:v", "high", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
with Pool() as pool:
    for k, buf in enumerate(pool.imap(render, TASKS, chunksize=6)):
        ff.stdin.write(buf)
        if k % 600 == 0: print(f"{k}/{len(TASKS)}", flush=True)
ff.stdin.close(); ff.wait()
if ff.returncode: sys.exit("ffmpeg a échoué")
print("OK", OUT, f"{total:.1f}s")
