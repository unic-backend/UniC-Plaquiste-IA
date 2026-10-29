"""Travail lourd sur PDF dans un PROCESSUS SÉPARÉ, à mémoire bornée.

Un plan d'architecte de 2 Mo peut contenir des centaines de milliers de traits : le dessiner coûte des centaines de Mo.
Fait ici, la mémoire est rendue au système dès la fin, et un plan trop lourd tue ce processus, jamais le serveur.
Usage : python pdfworker.py '<json>' → JSON sur la sortie standard. Aucune dépendance au reste de l'application.
"""
import base64
import gc
import io
import json
import re
import sys


def _open(path):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(path)


def _scale(page, wanted, max_side):
    w, h = page.get_size()
    return max(0.2, min(wanted, max_side / max(w, h, 1)))


def op_text(path, max_pages=2000):
    doc = _open(path)
    out = []
    try:
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            try:
                w, h = page.get_size()
                tp = page.get_textpage()
                try:
                    out.append({"t": (tp.get_text_range() or "").replace("\x00", " "), "w": float(w), "h": float(h)})
                finally:
                    tp.close()
            finally:
                page.close()
        return {"total": len(doc), "pages": out}
    finally:
        doc.close()


def op_images(path, pages, max_side=1568, quality=85):
    doc = _open(path)
    out = []
    try:
        for i in pages:
            if i >= len(doc):
                continue
            page = doc[i]
            try:
                img = page.render(scale=_scale(page, 2, max_side)).to_pil().convert("RGB")
            finally:
                page.close()
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            del img
            gc.collect()
            out.append(base64.b64encode(buf.getvalue()).decode())
        return {"images": out}
    finally:
        doc.close()


def _words(page, max_items):
    """Textes de la page avec leur position (fractions de la page, origine en haut à gauche) : sur un PDF exporté par un logiciel
    de dessin (AutoCAD, Revit, ArchiCAD…), ce sont les noms de pièces, surfaces et cotes EXACTS, plus fiables que l'image.
    Rend aussi les boîtes en points (gauche, bas, droite, haut) pour les mesures faites ici."""
    w, h = page.get_size()
    tp = page.get_textpage()
    out, boxes = [], []
    try:
        for i in range(min(tp.count_rects(), max_items)):
            left, bottom, right, top = tp.get_rect(i)
            text = " ".join((tp.get_text_bounded(left, bottom, right, top) or "").replace("\x00", " ").split())
            if text:
                out.append({"t": text[:120], "x": round(left / w, 3), "y": round(1 - top / h, 3)})
                boxes.append((text, left, bottom, right, top))
    finally:
        tp.close()
    return out, boxes


# ---------- mesures exactes d'un plan vectoriel (export AutoCAD, Revit, ArchiCAD…) ----------
# Les cloisons y sont des traits de couleur décrits dans la légende : on les mesure dans le fichier, au point près, au lieu de
# les estimer sur l'image. Les étiquettes des pièces (code, nom, cotes, surface) et le cartouche (niveau, niveaux concernés,
# hauteur, échelle) sont lus dans le texte. Rien n'est deviné : sans légende ou sans échelle, rien n'est mesuré.
_PARTITION = re.compile(r"cloison|doublage|ba\s?13|placo|partition|drywall|gypsum|plasterboard|stud", re.I)
_NOT_PARTITION = re.compile(r"sans\s+cloison|limite|axe|voile|b[ée]ton|fa[cç]ade", re.I)
_LEGEND_WORDS = re.compile(r"cloison|doublage|ba\s?13|placo|voile|mur|limite|plafond|partition|wall|ceiling|isolant|laine|"
                           r"gaine|porte|menuiserie", re.I)
_DIMS = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*[x×X]\s*(\d+(?:[.,]\d+)?)\s*m?\s*$")
_SURF = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)\s*$")
_CODE = re.compile(r"^[A-Za-z]{1,8}\d{0,3}[.\-]\d{1,3}[A-Za-z]?$")
_LEVEL = re.compile(r"^(?:RDC|rez[- ]de[- ]chauss[ée]e|R\s*\+\s*\d+(?:\s*(?:à|a|et|-)\s*R?\s*\+?\s*\d+)?|sous[- ]sol\s*\d*|SS\s*\d+)$", re.I)
_SCALE = re.compile(r"\b1\s*[/:]\s*(\d{2,4})\b")


def _num(s):
    return float(str(s).replace(",", "."))


def _strokes(page):
    """Traits du dessin : (couleur, épaisseur, x0, y0, x1, y1) en points, matrice de chaque objet appliquée ; et les rectangles
    remplis (fonds de pièce) pour caler l'échelle."""
    import ctypes
    import pypdfium2.raw as raw
    segs, rects = [], []
    for obj in page.get_objects(max_depth=3):
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        raw.FPDFPageObj_GetStrokeColor(obj.raw, r, g, b, a)
        width = ctypes.c_float()
        raw.FPDFPageObj_GetStrokeWidth(obj.raw, width)
        mode, stroke = ctypes.c_int(), ctypes.c_int()
        raw.FPDFPath_GetDrawMode(obj.raw, mode, stroke)
        m = obj.get_matrix()
        pts = []
        for i in range(raw.FPDFPath_CountSegments(obj.raw)):
            sg = raw.FPDFPath_GetPathSegment(obj.raw, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            raw.FPDFPathSegment_GetPoint(sg, x, y)
            pts.append((raw.FPDFPathSegment_GetType(sg), m.a * x.value + m.c * y.value + m.e, m.b * x.value + m.d * y.value + m.f))
        if mode.value and len(pts) in (4, 5):   # rectangle rempli
            xs, ys = [p[1] for p in pts], [p[2] for p in pts]
            if len({round(v, 1) for v in xs}) == 2 and len({round(v, 1) for v in ys}) == 2:
                rects.append((min(xs), min(ys), max(xs), max(ys)))
        if stroke.value:
            color = (r.value, g.value, b.value)
            for (_, x0, y0), (t1, x1, y1) in zip(pts, pts[1:]):
                if t1 == raw.FPDF_SEGMENT_LINETO:
                    segs.append((color, round(width.value, 2), x0, y0, x1, y1))
    return segs, rects


def _row_value(boxes, label_re, value_re):
    """Cartouche : valeur écrite à droite d'un intitulé, sur la même ligne (« Niveaux concernés … 33 »)."""
    for t, l, b, r, tp in boxes:
        if re.search(label_re, t, re.I):
            yc = (b + tp) / 2
            row = sorted((bx for bx in boxes if bx[1] > r - 1 and abs((bx[2] + bx[4]) / 2 - yc) < 4), key=lambda bx: bx[1])
            for bx in row:
                m = re.search(value_re, bx[0])
                if m:
                    return m.group(1)
            m = re.search(value_re, t[len(re.search(label_re, t, re.I).group(0)):])
            if m:
                return m.group(1)
    return None


def _rooms(boxes):
    """Étiquettes de pièce empilées (code / nom / cotes / surface) : code, nom, longueur × largeur et surface exacts. Chaque
    ligne est rattachée à la plus proche, d'abord à la verticale (deux étiquettes côte à côte ne se mélangent pas)."""
    def center(bx):
        return (bx[1] + bx[3]) / 2, (bx[2] + bx[4]) / 2

    def nearest(cx, cy, pick, up):
        cands = [(abs(center(o)[0] - cx) + 0.5 * abs(center(o)[1] - cy), o) for o in boxes if pick(o[0])
                 and abs(center(o)[0] - cx) < 40 and 0 < (center(o)[1] - cy if up else cy - center(o)[1]) < 16]
        return min(cands, key=lambda c: c[0])[1] if cands else None
    out = []
    for bx in boxes:
        m = _DIMS.match(bx[0])
        if not m:
            continue
        cx, cy = center(bx)
        name = nearest(cx, cy, lambda t: not (_DIMS.match(t) or _SURF.match(t) or _CODE.match(t)), up=True)   # y PDF vers le haut
        if name is None:
            continue
        code = nearest(*center(name), lambda t: bool(_CODE.match(t)), up=True)
        surf = nearest(cx, cy, lambda t: bool(_SURF.match(t)), up=False)
        out.append({"code": code[0] if code else None, "nom": name[0], "longueur_m": _num(m.group(1)), "largeur_m": _num(m.group(2)),
                    "surface_m2": _num(_SURF.match(surf[0]).group(1)) if surf else None, "_c": (cx, cy)})
    return out


def _merge_runs(segs):
    """Longueur d'un ensemble de traits sans compter deux fois un tronçon dessiné en double (traits alignés qui se recouvrent)."""
    import math
    lines, diagonals = {}, []
    for x0, y0, x1, y1 in segs:
        if abs(y1 - y0) < 0.5:
            lines.setdefault(("h", round((y0 + y1) / 2 * 2) / 2), []).append(tuple(sorted((x0, x1))))
        elif abs(x1 - x0) < 0.5:
            lines.setdefault(("v", round((x0 + x1) / 2 * 2) / 2), []).append(tuple(sorted((y0, y1))))
        else:
            diagonals.append(math.hypot(x1 - x0, y1 - y0))
    runs = list(diagonals)   # un tronçon en biais compte pour lui-même
    for spans in lines.values():
        spans.sort()
        start, end = spans[0]
        for a, b in spans[1:]:
            if a <= end + 0.5:
                end = max(end, b)
            else:
                runs.append(end - start)
                start, end = a, b
        runs.append(end - start)
    return sum(runs), runs


def _measure(page, boxes):
    """Cloisons mesurées par type de la légende, échelle, cartouche et pièces de la page. {} si rien à mesurer."""
    from statistics import median
    rooms = _rooms(boxes)
    w, h = page.get_size()
    scale_txt = _row_value(boxes, r"[ée]chelle|scale", r"1\s*[/:]\s*(\d{2,4})") or next(
        (m.group(1) for t, *_ in boxes for m in [_SCALE.search(t)] if m), None)
    cartouche = {"niveau": next((t for t, *_ in boxes if _LEVEL.match(t)), None),
                 "niveaux": _row_value(boxes, r"niveaux?\s+concern|nombre\s+de\s+niveaux", r"^\s*(\d{1,3})\s*$"),
                 "hauteur_m": _row_value(boxes, r"hauteur", r"(\d+(?:[.,]\d+)?)\s*m\b"),
                 "echelle": f"1/{scale_txt}" if scale_txt else None}
    cartouche = {k: (int(v) if k == "niveaux" else _num(v) if k == "hauteur_m" else v) for k, v in cartouche.items() if v}
    segs, rects = _strokes(page)
    # échelle : les cotes des pièces (longueur × largeur) comparées à leur fond rempli, sinon l'échelle écrite
    ratios = []
    for rm in rooms:
        cx, cy = rm["_c"]
        inside = [r for r in rects if r[0] < cx < r[2] and r[1] < cy < r[3] and (r[2] - r[0]) < w * 0.8]
        if inside:
            x0, y0, x1, y1 = min(inside, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
            a, b = rm["longueur_m"], rm["largeur_m"]
            pw, ph = x1 - x0, y1 - y0
            for la, lb in ((a, b), (b, a)):
                if la and lb and abs((pw / la) / (ph / lb) - 1) < 0.05:
                    ratios.append((la / pw + lb / ph) / 2)
                    break
    written = 0.0254 / 72 * int(scale_txt) if scale_txt else None
    calibrated = median(ratios) if len(ratios) >= 3 else None
    m_per_pt, source = ((written, "échelle écrite") if written and (not calibrated or abs(calibrated / written - 1) < 0.03)
                        else (calibrated, "cotes des pièces") if calibrated else (None, None))
    # légende : de petits traits de couleur ALIGNÉS en colonne, chacun suivi de son libellé (vocabulaire de légende) ; un trait du
    # plan voisin d'une étiquette de pièce n'en est pas un
    found = []
    for i, (color, width, x0, y0, x1, y1) in enumerate(segs):
        if abs(y1 - y0) > 0.5 or not 8 < abs(x1 - x0) < 90:
            continue
        right = max(x0, x1)
        label = next((t for t, l, b, r, tp in sorted(boxes, key=lambda bx: bx[1])
                      if 0 <= l - right < 40 and abs((b + tp) / 2 - y0) < 5), None)
        if label and _LEGEND_WORDS.search(label):
            found.append((i, round(min(x0, x1) / 3), label, color, width))
    columns = {}
    for f in found:
        columns.setdefault(f[1], []).append(f)
    legend, samples = [], set()
    for col in columns.values():
        if len(col) >= 2:
            for i, _, label, color, width in col:
                samples.add(i)
                legend.append({"libelle": label, "couleur": "#%02x%02x%02x" % color, "_color": color, "_width": width})
    types = [e for e in legend if _PARTITION.search(e["libelle"]) and not _NOT_PARTITION.search(e["libelle"])]
    cloisons = []
    if types and m_per_pt:
        for e in types:
            twins = [o for o in types if o["_color"] == e["_color"]]
            mine = [(x0, y0, x1, y1) for i, (c, wd, x0, y0, x1, y1) in enumerate(segs) if i not in samples and c == e["_color"]
                    and (len(twins) == 1 or abs(wd - e["_width"]) < 0.3)]
            length, runs = _merge_runs(mine)
            cloisons.append({"libelle": e["libelle"], "couleur": e["couleur"], "longueur_m": round(length * m_per_pt, 2),
                             "troncons": len(runs), "plus_long_m": round(max(runs, default=0) * m_per_pt, 2),
                             "troncons_m": [round(r * m_per_pt, 2) for r in runs if r * m_per_pt >= 0.05][:600]})
    out = {"pieces": [{k: v for k, v in rm.items() if k != "_c"} for rm in rooms], "cartouche": cartouche}
    if cloisons:
        out["cloisons"] = cloisons
    if types or m_per_pt:
        out["echelle"] = {"m_par_point": round(m_per_pt, 6) if m_per_pt else None, "source": source,
                          "legende": [e["libelle"] for e in types]}
    return out if (rooms or cloisons or cartouche or "echelle" in out) else {}


def op_page(path, index, max_side=1568, big_side=4000, quality=75, max_items=1500):
    """Une page de plan pour la lecture IA : vue d'ensemble + tuiles en haute définition (un grand format A1/A0 réduit à 1 568 px
    rend les cotes illisibles), et les textes positionnés. Rendu UNE fois, découpé ensuite : mémoire bornée."""
    doc = _open(path)
    try:
        page = doc[index]
        try:
            w, h = page.get_size()
            items, boxes = _words(page, max_items)
            try:
                mesures = _measure(page, boxes)
            except Exception:   # noqa: BLE001 — une mesure impossible ne bloque jamais la lecture de la page
                mesures = {}
            img = page.render(scale=max(0.2, min(2.0, big_side / max(w, h, 1)))).to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        doc.close()

    def b64(im):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    W, H = img.size
    tiles = []
    if max(W, H) > max_side * 1.3:   # grand format : tuiles qui se chevauchent un peu (une pièce coupée reste lisible)
        cols, rows = -(-W // int(max_side * 0.95)), -(-H // int(max_side * 0.95))
        tw, th = -(-W // cols), -(-H // rows)
        mx, my = int(tw * 0.06), int(th * 0.06)
        for r in range(rows):
            for c in range(cols):
                box = (max(0, c * tw - mx), max(0, r * th - my), min(W, (c + 1) * tw + mx), min(H, (r + 1) * th + my))
                tile = img.crop(box)
                tile.thumbnail((max_side, max_side))
                tiles.append({"b64": b64(tile), "box": [round(box[0] / W, 3), round(box[1] / H, 3), round(box[2] / W, 3),
                                                        round(box[3] / H, 3)]})
                del tile
    img.thumbnail((max_side, max_side))
    overview = b64(img)
    del img
    gc.collect()
    return {"overview": overview, "tiles": tiles, "words": items, "w": float(w), "h": float(h), "mesures": mesures}


def op_ocr(path, index, max_side=3000, lang="fra+eng"):
    import pytesseract
    doc = _open(path)
    try:
        page = doc[index]
        try:
            img = page.render(scale=_scale(page, 300 / 72, max_side)).to_pil()
        finally:
            page.close()
    finally:
        doc.close()
    return {"text": pytesseract.image_to_string(img, lang=lang).strip()}


OPS = {"text": op_text, "images": op_images, "ocr": op_ocr, "page": op_page}

if __name__ == "__main__":
    req = json.loads(sys.argv[1])
    try:
        res = OPS[req.pop("op")](**req)
    except MemoryError:
        res = {"error": "memory"}
    except Exception as exc:   # noqa: BLE001 — renvoyé au serveur, jamais d'exception non gérée
        res = {"error": type(exc).__name__}
    sys.stdout.write(json.dumps(res))
