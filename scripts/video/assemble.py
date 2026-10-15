"""Assemble les tronçons (chunk-000.mp4, chunk-001.mp4…) en une seule vidéo, sans ré-encodage : python assemble.py dossier sortie.mp4"""
import subprocess, sys
from pathlib import Path

folder, out = Path(sys.argv[1]), sys.argv[2]
parts = sorted(folder.glob("**/*.mp4"))
if not parts:
    sys.exit("aucun tronçon à assembler")
listing = folder / "concat.txt"
listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", out], check=True)
print("OK", out, len(parts), "tronçons")
