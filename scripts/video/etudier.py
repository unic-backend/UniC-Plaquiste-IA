"""Étudier une vidéo de référence : une image tous les quarts de seconde, rangées en planches à regarder UNE PAR UNE
avant d'écrire le brief (survoler une référence, c'est la refaire de travers). Une vidéo de tiers sert à étudier, jamais à republier.
Usage : python etudier.py reference.mp4 dossier [images_par_seconde=4]"""
import pathlib
import subprocess
import sys


def grille(largeur: int, hauteur: int) -> tuple[int, int, int]:
    """(colonnes, lignes, largeur d'une image) : des planches d'environ 1920 px de large, lisibles d'un coup d'œil."""
    if hauteur > largeur:
        return 7, 2, 270
    if hauteur == largeur:
        return 5, 3, 380
    return 4, 4, 480


def filtre(largeur: int, hauteur: int, ips: float = 4.0) -> str:
    cols, lignes, w = grille(largeur, hauteur)
    return f"fps={ips:g},scale={w}:-2,tile={cols}x{lignes}:padding=4:margin=4"


def main(video: str, dossier: str, ips: float = 4.0) -> int:
    if not 0 < ips <= 30:
        raise SystemExit("images par seconde : entre 0 et 30")
    taille = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0:s=x", video], capture_output=True, text=True, check=True).stdout.strip()
    w, h = (int(x) for x in taille.split("x")[:2])
    out = pathlib.Path(dossier)
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", filtre(w, h, ips), str(out / "%03d.jpg")], check=True)
    n = len(list(out.glob("*.jpg")))
    cols, lignes, _ = grille(w, h)
    print(f"{n} planches dans {out} ({cols * lignes} images par planche, {ips:g} images/s) : les regarder toutes, dans l'ordre.")
    return n


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 4.0)
