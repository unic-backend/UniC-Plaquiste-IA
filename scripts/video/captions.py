"""Sous-titres « reels » : groupes de 3 mots en MAJUSCULES, le mot prononcé en jaune.
Entrée : mots.json [{"w","s","e"}] (faster-whisper, word_timestamps). Sortie : fichier .ass à incruster avec ffmpeg :
  ffmpeg -i video.mp4 -vf "ass=sous-titres.ass" -c:a copy sortie.mp4
Usage : python captions.py mots.json sous-titres.ass [largeur] [hauteur]"""
import json
import sys

JAUNE, BLANC = "&H0000D7FF&", "&H00FFFFFF&"   # couleurs ASS (BBGGRR)


def t(sec: float) -> str:
    cs = max(0, round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def groups(words, size=3, gap=0.6):
    """Coupe en groupes de `size` mots au plus, ou à chaque silence de plus de `gap` secondes."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) == size or w["s"] - cur[-1]["e"] > gap):
            out.append(cur)
            cur = []
        cur.append(w)
    return out + ([cur] if cur else [])


def ass(words, w=1080, h=1920) -> str:
    fs = round(h * 0.045)
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, "
            "MarginL, MarginR, MarginV, BorderStyle, Outline, Shadow\n"
            f"Style: Reel,Inter Display Black,{fs},{BLANC},&H00000000&,&H80000000&,-1,2,60,60,{round(h * 0.28)},1,{max(3, fs // 12)},2\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Text\n")
    lines = []
    for g in groups(words):
        for i, cur in enumerate(g):
            end = g[i + 1]["s"] if i + 1 < len(g) else cur["e"] + 0.15
            text = " ".join((f"{{\\c{JAUNE}}}" if j == i else f"{{\\c{BLANC}}}") + x["w"].upper()
                            for j, x in enumerate(g))
            lines.append(f"Dialogue: 0,{t(cur['s'])},{t(end)},Reel,{text}")
    return head + "\n".join(lines) + "\n"


if __name__ == "__main__":
    words = json.load(open(sys.argv[1], encoding="utf-8"))
    w, h = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1080, 1920)
    open(sys.argv[2], "w", encoding="utf-8").write(ass(words, w, h))
    # contrôle : chaque mot a un seul passage en jaune, dans l'ordre
    assert sum(1 for _ in groups(words)) and len([l for l in ass(words, w, h).splitlines() if l.startswith("Dialogue")]) == len(words)
