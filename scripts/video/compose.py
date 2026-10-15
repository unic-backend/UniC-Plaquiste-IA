"""Montage final : page (caméra sous-pixel) + incrustations -> MP4 1080x1920, 60 i/s, sans mélange d'images (texte net). Sortie plafonnée à ~25 Mo."""
import json, subprocess, sys
from multiprocessing import Pool
from PIL import Image

FRAMES, OVD, OUT = sys.argv[1:4]
M = json.load(open(f"{FRAMES}/meta.json")); O = json.load(open(f"{OVD}/list.json"))
W, H, S, CAP, NF, P, TOTAL = M["W"], M["H"], M["SCALE"], M["CAP"], M["frames"], O["P"], O["total"]
OW, OH, MARGIN = 1080, 1920, 1.008
ACT = set(O["act"]); N = round(TOTAL * 60)

def render(n):
    t = n / 60 - P
    if t >= M["endAt"] + 1.2:
        base = Image.new("RGB", (OW, OH), (2, 8, 58))
    else:
        i = min(NF - 1, max(0, round(max(0.0, t) * CAP)))
        r, z = M["meta"][i]
        z = max(1.0, z) * MARGIN; cw, ch = W / z, H / z
        x0, y0 = (W - cw) / 2, min(max((H - ch) / 2 + r, 0), H - ch)
        base = Image.open(f"{FRAMES}/{i:05d}.jpg").convert("RGB").resize((OW, OH), Image.LANCZOS, box=(x0 * S, y0 * S, (x0 + cw) * S, (y0 + ch) * S))
    if n in ACT:
        base = base.convert("RGBA"); base.alpha_composite(Image.open(f"{OVD}/{n:05d}.png").convert("RGBA")); base = base.convert("RGB")
    return base.tobytes()

kbps = int(24e6 * 8 / TOTAL / 1000)                       # ~24 Mo au maximum
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-framerate", "60", "-i", "-",
    "-vf", "eq=contrast=1.02:saturation=1.05,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-maxrate", f"{min(kbps, 9000)}k",
    "-bufsize", f"{min(kbps, 9000) * 2}k", "-profile:v", "high", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
with Pool() as pool:
    for k, buf in enumerate(pool.imap(render, range(N), chunksize=6)):
        ff.stdin.write(buf)
        if k % 600 == 0: print(f"{k}/{N}", flush=True)
ff.stdin.close(); ff.wait()
if ff.returncode: sys.exit("ffmpeg a échoué")
print("OK", OUT)
