"""Scénario d'une vidéo (JSON) : validation stricte, partagée par make.py. Le scénario vient de l'appli (donc de Claude) : on ne lui fait pas confiance.

Forme : {"format": "vertical|horizontal|square", "scenes": [ {type: title|text|photo|gallery|stats|quote|page|outro|clip|typewriter|kinetic|checklist|neon|slogan, seconds, ...}, ... ]}
Ancienne forme (url + chapters) acceptée : convertie en titre + page + fin.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

FORMATS = {"vertical": (360, 640), "horizontal": (640, 360), "square": (360, 360)}       # px CSS ; ×3 = 1080×1920, 1920×1080, 1080×1080
SEL_RE = re.compile(r"^[#.][A-Za-z][\w-]{0,40}$")
HOST_OK = re.compile(r"^([a-z0-9-]+\.)*(unicplaquiste\.com|netlify\.app)$")
IMG_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,80}\.(webp|jpg|jpeg|png)$")
IMG_BASE = "https://www.unicplaquiste.com/images/"
CTRL = re.compile(r"[\x00-\x1f\x7f<>]")
THEMES = ("unic", "night", "light", "earth", "ocean", "sunset", "noir", "luxe", "papier", "pastel", "neon", "chantier")   # palettes de scenes.html : le sujet de la vidéo choisit son ambiance
TYPES = ("title", "text", "photo", "gallery", "stats", "quote", "page", "outro", "clip", "typewriter", "kinetic", "checklist", "neon", "slogan",
         "counter", "flow", "wave", "chat", "badge", "lottie", "motion")
# « motion » : animation libre dessinée par l'IA (SVG animé en CSS), nettoyée par le serveur (motion_svg.py) ; revérifiée ici (aucun script ni rien d'externe).
MOTION_MAX = 60_000
MOTION_BAD = re.compile(r"<\s*(script|foreignObject|iframe|image|img|a|object|embed|link|meta)\b|\son\w+\s*=|javascript:|data:|@import|"
                        r"(?:href|src)\s*=\s*['\"](?!#)|url\s*\(\s*['\"]?\s*(?!#)", re.I)
# Panneaux animés (motion design) : compteur, schéma A → B → C, onde sonore, bulle de commentaire, badge ; en scène, en incrustation ou en haut d'un écran divisé.
PANEL_TYPES = ("counter", "flow", "wave", "chat", "badge", "lottie")
# Animations vectorielles Lottie (lottie-web « light », sans expressions) : celles du moteur (dossier lottie/) ou celles du patron (lien https).
LOTTIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lottie")
BUILTIN_LOTTIE = tuple(sorted(f[:-5] for f in os.listdir(LOTTIE_DIR) if f.endswith(".json"))) if os.path.isdir(LOTTIE_DIR) else ()
MAX_LOTTIE_BYTES = 3 * 1024 * 1024
FX_TYPES = ("typewriter", "kinetic", "checklist", "neon", "slogan", *PANEL_TYPES)
LAYOUTS = ("full", "split")      # split : la personne filmée en bas, les animations en haut (sous-titres à la jonction)
MAX_PANELS = 400
# Effets « cinéma » : texte tapé au clavier, titre dont le dernier mot arrive en or, liste cochée sur verre dépoli, titre néon, carte slogan.
# Les quatre premiers peuvent aussi s'incruster sur un clip (clé « overlay » d'une scène clip) : le texte passe alors sur les images filmées.
OVERLAY_TYPES = ("typewriter", "kinetic", "checklist", "neon", *PANEL_TYPES)
# Montage d'une scène « clip » (edit.py) : vitesse, étalonnage, cadrage, zoom, arrêt sur image, écran partagé, transition d'entrée.
GRADES = ("cinema", "warm", "night", "crisp", "bw")
ZOOMS = ("in", "out", "punch")
TRANSITIONS = ("fade", "cut", "flash", "slide")
# Garde-fous techniques seulement (pas un plafond métier) : la durée n'est limitée que par le temps de calcul GitHub. Au-delà, on coupe en tronçons (chunks()).
MAX_SCENES, MAX_TOTAL = 5000, 43200.0


def _txt(v, n: int) -> str:
    return CTRL.sub("", str(v or "")).strip()[:n]


def _secs(v, lo: float, hi: float, dflt: float) -> float:
    try:
        return round(min(hi, max(lo, float(v))), 2)
    except (TypeError, ValueError):
        return dflt


def stat_value(v) -> int | float | None:
    """Chiffre d'une scène « chiffres » : décimales gardées (2,5 % reste 2,5), négatif permis (−15 %), borné ; None si ce n'est pas un nombre."""
    import math
    try:
        f = round(float(v), 2)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    f = min(max(f, -10 ** 9), 10 ** 9)
    return int(f) if f == int(f) else f


def _img(v) -> str:
    n = str(v or "")
    if not IMG_RE.match(n) or ".." in n:
        raise ValueError(f"image refusée : {n[:30]}")
    return (os.environ.get("VIDEO_IMG_BASE") or IMG_BASE) + n


def _media_url(raw) -> str:
    """Adresse d'un média généré (clip ou image d'IA) : https obligatoire, jamais une adresse IP ni localhost, pas d'identifiants dans l'adresse.
    (Le serveur ne la prend que dans la réponse du fournisseur ; le moteur la revalide.)"""
    import ipaddress
    u = urlparse(str(raw or ""))
    local = os.environ.get("VIDEO_ALLOW_LOCAL") == "1" and u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
    if local:
        return str(raw)
    host = (u.hostname or "").lower()
    ip = True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        ip = False
    if u.scheme != "https" or not host or ip or host == "localhost" or host.endswith(".local") or u.username or u.password or len(str(raw)) > 2000:
        raise ValueError("adresse de média refusée")
    return str(raw)


def _url(raw) -> str:
    u = urlparse(str(raw or ""))
    local = os.environ.get("VIDEO_ALLOW_LOCAL") == "1" and u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
    if not local and not (u.scheme == "https" and u.hostname and HOST_OK.match(u.hostname) and not u.username):
        raise ValueError("adresse refusée : seul unicplaquiste.com (ou un aperçu Netlify) est filmé")
    return str(raw)


def _lines_of(v, n: int, k: int, upper: bool = False) -> list[str]:
    out = [_txt(x, n) for x in (v if isinstance(v, list) else [v]) if _txt(x, n)][:k]
    return [x.upper() for x in out] if upper else out


def _fx(s: dict, t: str, overlay: bool = False) -> dict:
    """Scène d'effet (ou incrustation d'un clip si `overlay`) : textes bornés, fond facultatif (photo du catalogue ou média https)."""
    if t == "typewriter":
        lines = _lines_of(s.get("lines"), 60, 3)
        if not lines:
            raise ValueError("machine à écrire : texte vide")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 2.5, 12, 4), "lines": lines}
    elif t == "kinetic":
        lines = _lines_of(s.get("lines"), 26, 3, upper=True)
        if not lines:
            raise ValueError("titre animé : texte vide")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 2, 10, 3.5), "lines": lines, "tag": _txt(s.get("tag"), 12).upper(), "place": _txt(s.get("place"), 28).upper()}
    elif t == "checklist":
        items = _lines_of(s.get("items"), 40, 5)
        if not items:
            raise ValueError("liste cochée : aucun élément")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 3, 12, max(4.0, 1.4 + 0.8 * len(items))), "heading": _txt(s.get("heading"), 40).upper(), "items": items}
    elif t == "neon":
        lines = _lines_of(s.get("lines"), 16, 2, upper=True)
        if not lines:
            raise ValueError("néon : texte vide")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 2, 8, 3), "lines": lines, "tag": _txt(s.get("tag"), 12).upper()}
    elif t == "counter":
        v = stat_value(s.get("value"))
        if v is None:
            raise ValueError("compteur : nombre manquant")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 1.5, 10, 3), "value": v, "suffix": _txt(s.get("suffix"), 6), "label": _txt(s.get("label"), 28).upper()}
    elif t == "flow":
        steps = _lines_of(s.get("steps"), 18, 4)
        if len(steps) < 2:
            raise ValueError("schéma : au moins 2 étapes")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 2, 12, 1.2 + 0.8 * len(steps)), "steps": steps}
    elif t == "lottie":
        if s.get("anim") in BUILTIN_LOTTIE:
            src = {"anim": s["anim"]}
        elif s.get("url"):
            src = {"url": _media_url(s["url"])}
        else:
            raise ValueError("animation : ni animation du moteur ni lien")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 1.5, 10, 2.5), **src, "lines": _lines_of(s.get("lines"), 24, 2), "loop": s.get("loop") is True}
    elif t in ("wave", "chat", "badge"):
        lines = _lines_of(s.get("lines"), 30 if t == "chat" else 24, 2)
        if t != "wave" and not lines:
            raise ValueError(f"{t} : texte vide")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 1.5, 10, 4 if t == "chat" else 3), "lines": lines}
    else:   # slogan (carte de fin, jamais en incrustation)
        l1, l2 = _txt(s.get("l1"), 30).upper(), _txt(s.get("l2"), 30).upper()
        if not (l1 or l2):
            raise ValueError("slogan vide")
        out = {"type": t, "seconds": _secs(s.get("seconds"), 4, 12, 7), "l1": l1, "l2": l2, "brand": _txt(s.get("brand"), 30).upper(),
               "lines": _lines_of(s.get("lines"), 40, 4)}
    if not overlay and t not in ("slogan", "lottie") and (s.get("url") or s.get("image")):   # le lien d'une animation n'est pas un fond
        out["bg"] = _media_url(s.get("url")) if s.get("url") else _img(s.get("image"))
        out["reveal"] = "dots" if s.get("reveal") == "dots" else ""
    return out


def sanitize_lottie(d) -> dict:
    """Animation Lottie sûre pour le rendu : structure vérifiée, AUCUNE ressource externe (images par lien, polices distantes) ;
    seules les images intégrées (data:) et les compositions internes restent. Les expressions ne s'exécutent pas (lottie « light »)."""
    if not isinstance(d, dict) or not isinstance(d.get("layers"), list) or not d["layers"] or len(d["layers"]) > 500:
        raise ValueError("animation Lottie invalide")
    try:
        fr, ip, op, w, h = (float(d[k]) for k in ("fr", "ip", "op", "w", "h"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("animation Lottie invalide")
    if not (1 <= fr <= 120 and 0 < op - ip <= fr * 120 and 0 < w <= 8000 and 0 < h <= 8000):
        raise ValueError("animation Lottie hors limites")
    out = dict(d)
    assets = []
    for a in d.get("assets") or []:
        if not isinstance(a, dict):
            continue
        if "layers" in a:                                   # composition interne
            assets.append(a)
        elif str(a.get("p") or "").startswith("data:image/") and not a.get("u"):
            assets.append(a)                                # image intégrée ; un lien vers l'extérieur est écarté
    out["assets"] = assets
    out.pop("fonts", None)                                  # polices distantes : jamais chargées
    return out


def _panels(raw, secs: float) -> list:
    """Suite d'animations sur un film : [[début dans la scène, avance dans l'animation, animation], …], triée.
    « avance » : une animation commencée avant ce plan (coupe des silences) reprend où elle en était, sans recommencer."""
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw[:MAX_PANELS]:
        if not (isinstance(p, (list, tuple)) and len(p) == 3 and isinstance(p[2], dict) and p[2].get("type") in OVERLAY_TYPES):
            continue
        try:
            fx = _fx(p[2], p[2]["type"], overlay=True)
        except ValueError:
            continue
        a = _secs(p[0], 0, secs, -1)
        if 0 <= a < secs:
            out.append([a, _secs(p[1], 0, 3600, 0), fx])
    return sorted(out, key=lambda x: x[0])


def _edits(s: dict, secs: float) -> dict:
    """Montage d'un clip, seulement ce qui change quelque chose (valeurs bornées ; inconnu = ignoré)."""
    e: dict = {}
    speed = _secs(s.get("speed"), 0.25, 4, 1)
    if speed != 1:
        e["speed"] = speed
    elif s.get("sound") is True:      # son du film (parole, ambiance) : seulement à vitesse normale (un ralenti parlé serait déformé)
        e["sound"] = True
    if s.get("grade") in GRADES:
        e["grade"] = s["grade"]
    f = s.get("focus")
    if isinstance(f, dict):
        x, y = _secs(f.get("x"), 0, 1, 0.5), _secs(f.get("y"), 0, 1, 0.5)
        if (x, y) != (0.5, 0.5):
            e["focus"] = {"x": x, "y": y}
    if s.get("zoom") in ZOOMS:
        e["zoom"], e["zoom_amount"] = s["zoom"], _secs(s.get("zoom_amount"), 1.05, 1.6, 1.2)
    freeze = _secs(s.get("freeze"), 0, 3, 0)
    if 0 < freeze <= secs - 1:
        e["freeze"] = freeze
    if s.get("transition") in TRANSITIONS and s["transition"] != "fade":
        e["transition"] = s["transition"]
    sl = s.get("split")
    if isinstance(sl, dict) and sl.get("url"):     # écran partagé : second film (avant/après), même validation d'adresse
        e["split"] = {"url": _media_url(sl["url"]), "start": _secs(sl.get("start"), 0, 36000, 0)}
    return e


def _scene(s: dict) -> dict:
    t = s.get("type")
    if t not in TYPES:
        raise ValueError(f"type de scène inconnu : {str(t)[:20]}")
    if t in FX_TYPES:
        return _fx(s, t)
    if t == "motion":
        svg = s.get("svg")
        if not isinstance(svg, str) or not svg.lstrip().startswith("<svg") or len(svg) > MOTION_MAX or MOTION_BAD.search(svg):
            raise ValueError("animation libre refusée (SVG invalide ou ressource externe)")
        return {"type": t, "seconds": _secs(s.get("seconds"), 2, 15, 5), "svg": svg}
    if t == "title":
        return {"type": t, "seconds": _secs(s.get("seconds"), 2.5, 8, 4), "l1": _txt(s.get("l1"), 24).upper(), "l2": _txt(s.get("l2"), 24).upper(), "sub": _txt(s.get("sub"), 40).upper()}
    if t == "text":
        b = [_txt(x, 70) for x in (s.get("bullets") or []) if _txt(x, 70)][:4]
        if not b:
            raise ValueError("scène texte sans contenu")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 10, 5), "heading": _txt(s.get("heading"), 40), "bullets": b}
    if t == "clip":
        out = {"type": t, "seconds": _secs(s.get("seconds"), 0.5, 30, 5), "url": _media_url(s.get("url")), "start": _secs(s.get("start"), 0, 36000, 0)}   # 0,5 s : plans collés d'une coupe des silences
        ov = s.get("overlay")
        if isinstance(ov, dict) and ov.get("type") in OVERLAY_TYPES:   # texte incrusté sur le film : même durée que le clip
            out["overlay"] = {**_fx(ov, ov["type"], overlay=True), "seconds": out["seconds"]}
        out.update(_edits(s, out["seconds"]))
        panels = _panels(s.get("panels"), out["seconds"])
        if panels:
            out["panels"] = panels
        if s.get("layout") == "split":           # écran divisé : jamais avec l'avant | après (deux découpages de l'image)
            out["layout"] = "split"
            out.pop("split", None)
        return out
    if t == "photo":
        return {"type": t, "seconds": _secs(s.get("seconds"), 2.5, 8, 4), "src": _media_url(s.get("url")) if s.get("url") else _img(s.get("image")), "caption": _txt(s.get("caption"), 60),
                "dir": s.get("direction") if s.get("direction") in ("in", "out", "left", "right") else "in"}
    if t == "gallery":
        imgs = [_img(x) for x in (s.get("images") or [])][:6]
        if len(imgs) < 2:
            raise ValueError("galerie : au moins 2 images")
        return {"type": t, "seconds": _secs(s.get("seconds"), 4, 14, 2.4 * len(imgs)), "srcs": imgs, "caption": _txt(s.get("caption"), 60)}
    if t == "stats":
        items = []
        for it in (s.get("items") or [])[:4]:
            v = stat_value(it.get("value")) if isinstance(it, dict) else None
            if v is None:
                continue
            items.append({"value": v, "suffix": CTRL.sub("", str(it.get("suffix") or ""))[:6], "label": _txt(it.get("label"), 28)})
        if len(items) < 2:
            raise ValueError("chiffres : au moins 2")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 9, 5), "items": items}
    if t == "quote":
        q = _txt(s.get("text"), 220)
        if not q:
            raise ValueError("citation vide")
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 10, 6), "text": q, "author": _txt(s.get("author"), 40)}
    if t == "outro":
        return {"type": t, "seconds": _secs(s.get("seconds"), 3, 8, 5), "lines": [_txt(x, 60) for x in (s.get("lines") or [])][:6]}
    ch = []
    for c in (s.get("chapters") or [])[:8]:
        sel = str((c or {}).get("selector") or "")
        if not SEL_RE.match(sel):
            raise ValueError(f"sélecteur refusé : {sel[:30]}")
        ch.append({"selector": sel, "label": _txt(c.get("label"), 24) or "Suite", "seconds": _secs(c.get("seconds"), 2.5, 9, 4)})
    if not ch:
        raise ValueError("scène page sans chapitre")
    return {"type": t, "url": _url(s.get("url")), "hero_seconds": _secs(s.get("hero_seconds"), 2, 6, 4.4), "chapters": ch,
            "seconds": 0}   # durée réelle fixée par la capture


def scene_seconds(s: dict) -> float:
    """Durée prévue d'une scène (une scène « page » : accueil + chapitres + descente finale)."""
    return s["seconds"] or (s["hero_seconds"] + sum(c["seconds"] for c in s["chapters"]) + 2.5)


def chunks(scenes: list[dict], target: float = 90.0, max_chunks: int = 250) -> list[list[dict]]:
    """Coupe la vidéo en tronçons d'environ `target` secondes (jamais au milieu d'une scène) : chacun se rend sur sa propre machine, puis on assemble.
    Au plus `max_chunks` tronçons (limite des matrices GitHub) : plus la vidéo est longue, plus les tronçons grossissent."""
    total = sum(scene_seconds(s) for s in scenes)
    target = max(float(target), total / max_chunks)
    out: list[list[dict]] = [[]]; acc = 0.0
    for s in scenes:
        if out[-1] and acc >= target:
            out.append([]); acc = 0.0
        out[-1].append(s); acc += scene_seconds(s)
    return out


DUCKS = ("light", "normal", "strong")


def _audio(a) -> dict | None:
    """Bande son facultative : musique (https), voix (https, ex. ElevenLabs), clavier des textes tapés, force de la baisse de la musique sous la voix."""
    if not isinstance(a, dict):
        return None
    out: dict = {}
    m = a.get("music")
    if isinstance(m, dict) and m.get("url"):
        out["music"] = {"url": _media_url(m["url"]), "start": _secs(m.get("start"), 0, 3600, 0), "volume": _secs(m.get("volume"), 0, 2, 1)}
    v = a.get("voice")
    if isinstance(v, dict) and v.get("url"):
        out["voice"] = {"url": _media_url(v["url"]), "offset": _secs(v.get("offset"), 0, 43200, 0), "volume": _secs(v.get("volume"), 0, 2, 1)}
    out["keys"] = bool(a.get("keys", True))
    out["duck"] = a.get("duck") if a.get("duck") in DUCKS else "normal"
    return out if ("music" in out or "voice" in out or out["keys"]) else None


def _voice_seg(sc: dict, raw: dict) -> dict:
    """Morceau de la piste voix lu pendant la scène : « voice »: [début, fin] en secondes (60 s au plus), « voice_at » : décalage dans la scène."""
    seg = raw.get("voice")
    if isinstance(seg, (list, tuple)) and len(seg) == 2:
        a, b = _secs(seg[0], 0, 3600, -1), _secs(seg[1], 0, 3600, -1)
        if 0 <= a < b <= a + 60:
            sc["voice"] = [a, b]
            sc["voice_at"] = _secs(raw.get("voice_at"), 0, 30, 0)
    return sc


CAP_WORDS, CAP_CHARS, CAP_PAUSE = 3, 16, 0.35     # sous-titres : 3 mots et 16 caractères au plus par carton ; une pause ouvre un nouveau carton
MAX_CAP_WORDS = 4000


def caption_groups(words, seconds: float) -> list[list]:
    """Mots datés [[début, fin, mot], …] (instants dans la scène) -> cartons de sous-titres [[début, fin, texte], …].
    Un carton : 1 à 3 mots dits ensemble ; il reste affiché jusqu'au suivant (sauf longue pause). Fonction pure, testée."""
    if not isinstance(words, list) or seconds <= 0:
        return []
    ws = []
    for w in words[:MAX_CAP_WORDS]:
        if not (isinstance(w, (list, tuple)) and len(w) == 3):
            continue
        a, b, txt = _secs(w[0], 0, seconds, -1), _secs(w[1], 0, seconds, -1), _txt(w[2], 30)
        if a >= 0 and b >= a and txt and a < seconds:
            ws.append((a, max(b, a + 0.05), txt))
    ws.sort(key=lambda x: x[0])
    groups: list[list] = []
    cur: list = []
    for a, b, txt in ws:
        if cur and (len(cur) >= CAP_WORDS or sum(len(x[2]) + 1 for x in cur) + len(txt) > CAP_CHARS
                    or a - cur[-1][1] > CAP_PAUSE or cur[-1][2][-1] in ".!?,;:…"):
            groups.append(cur)
            cur = []
        cur.append((a, b, txt))
    if cur:
        groups.append(cur)
    out = []
    for k, g in enumerate(groups):
        t0, t1 = g[0][0], g[-1][1] + 0.25
        if k + 1 < len(groups) and groups[k + 1][0][0] - g[-1][1] < 0.6:
            t1 = groups[k + 1][0][0]                 # enchaîné : pas de clignotement entre deux cartons
        out.append([round(t0, 2), round(min(seconds, t1), 2), " ".join(x[2] for x in g)])
    return out


def _caps(sc: dict, raw: dict) -> dict:
    """Sous-titres mot à mot d'une scène (parole du film ou voix off), si fournis."""
    if raw.get("captions") and sc["type"] != "page":
        g = caption_groups(raw["captions"], scene_seconds(sc))
        if g:
            sc["caps"] = g
    return sc


def clean(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("scénario invalide")
    if "scenes" not in raw:   # ancienne forme : titre + page + fin
        t = [_txt(x, 24) for x in (raw.get("title") or ["UNIC", "PLAQUISTE"])]
        raw = {"format": "vertical", "scenes": [{"type": "title", "l1": t[0], "l2": t[1] if len(t) > 1 else "", "sub": raw.get("subtitle", "")},
                                                 {"type": "page", "url": raw.get("url"), "hero_seconds": raw.get("hero_seconds"), "chapters": raw.get("chapters")},
                                                 {"type": "outro", "lines": raw.get("end")}]}
    fmt = raw.get("format") if raw.get("format") in FORMATS else "vertical"
    raw_scenes = raw.get("scenes") or []
    if not isinstance(raw_scenes, list):
        raise ValueError("liste de scènes invalide")
    if len(raw_scenes) > MAX_SCENES:
        raise ValueError(f"trop de scènes ({MAX_SCENES} au maximum)")
    scenes = [_caps(_voice_seg(_scene(s), s), s) for s in raw_scenes if isinstance(s, dict)]
    if not scenes:
        raise ValueError("aucune scène")
    est = sum(scene_seconds(s) for s in scenes)
    if est > MAX_TOTAL:
        raise ValueError("vidéo trop longue (12 heures au maximum)")
    fps = raw.get("fps") if raw.get("fps") in (24, 30, 60) else 60
    theme = raw.get("theme") if raw.get("theme") in THEMES else "unic"
    out = {"format": fmt, "fps": fps, "theme": theme, "scenes": scenes}
    au = _audio(raw.get("audio"))
    if au:
        out["audio"] = au
    return out
