"""Lecture de fichiers CAD/BIM : DXF (AutoCAD, ArchiCAD, SketchUp…) et IFC (Revit, ArchiCAD, Allplan…).

Le résultat est un texte structuré (calques, pièces, surfaces, cloisons, annotations) qui rejoint l'index des documents
et que `plans.analyze` lit comme n'importe quel plan. Surfaces et longueurs sont calculées ici, géométrie à l'appui.
DWG : format fermé, non lu (voir `DWG_MESSAGE`).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger("unic.cad")

DWG_MESSAGE = "DWG non lu (format fermé). Exporte le plan en DXF ou en PDF depuis AutoCAD/ArchiCAD/Revit, puis renvoie-le."
CAD_EXT = {".dxf", ".ifc"}

# $INSUNITS → mètres
UNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}
UNIT_NAMES = {1: "pouces", 2: "pieds", 4: "mm", 5: "cm", 6: "m", 7: "km"}
WALL_LAYER = re.compile(r"mur|wall|cloison|partition|doublage|stud|drywall|gypsum|a-wall", re.I)
MAX_ROOMS, MAX_TEXTS = 80, 150


def _area(pts: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def _inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y, ok = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            ok = not ok
    return ok


def _clean_text(t: str) -> str:
    t = re.sub(r"\\[A-Za-z][^;]*;|[{}]", "", t or "")   # codes de mise en forme MTEXT
    return re.sub(r"\s+", " ", t.replace("\\P", " ")).strip()


def read_dxf(path: Path) -> str:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    note = ""
    ents = list(msp)
    xs = [v for e in ents if e.dxftype() in ("LINE", "LWPOLYLINE")
          for v in ([e.dxf.start.x, e.dxf.end.x] if e.dxftype() == "LINE" else [p[0] for p in e.get_points("xy")])]
    span = (max(xs) - min(xs)) if xs else 0
    if code in UNITS:
        k = UNITS[code]
    else:   # unité non déclarée : on devine d'après l'étendue du dessin et on le dit
        k, guess = (0.001, "mm") if span > 500 else ((0.01, "cm") if span > 100 else (1.0, "m"))
        note = f"Unité non déclarée dans le fichier : supposée en {guess} d'après la taille du dessin (à confirmer)."
    unit = UNIT_NAMES.get(code, "supposée")

    layers = Counter(e.dxf.layer for e in ents)
    polys, texts, dims, wall_len = [], [], [], 0.0
    for e in ents:
        t = e.dxftype()
        layer = e.dxf.layer
        if t == "LWPOLYLINE":
            pts = [(p[0] * k, p[1] * k) for p in e.get_points("xy")]
            if e.closed and len(pts) >= 3:
                polys.append((layer, pts))
            elif WALL_LAYER.search(layer) and len(pts) >= 2:
                wall_len += sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))
        elif t == "LINE" and WALL_LAYER.search(layer):
            s, d = e.dxf.start, e.dxf.end
            wall_len += ((s.x - d.x) ** 2 + (s.y - d.y) ** 2) ** 0.5 * k
        elif t in ("TEXT", "MTEXT"):
            txt = _clean_text(e.dxf.text if t == "TEXT" else e.text)
            if txt:
                ins = e.dxf.insert
                texts.append((txt, (ins.x * k, ins.y * k), layer))
        elif t == "DIMENSION":
            m = getattr(e.dxf, "actual_measurement", None)
            if m:
                dims.append(round(float(m) * k, 2))

    rooms = []
    for layer, pts in polys:
        a = _area(pts)
        if 0.5 <= a <= 2000:
            label = ", ".join(txt for txt, p, _ in texts if _inside(p, pts))[:80]
            rooms.append((a, layer, label))
    rooms.sort(reverse=True)

    out = [f"[CAD DXF] {path.name} — unité du fichier : {unit}. {note}".strip(),
           "Calques (entités) : " + ", ".join(f"{n} ({c})" for n, c in layers.most_common(40))]
    if rooms:
        out.append("Contours fermés (surface calculée depuis la géométrie, nom = texte placé dedans) :")
        out += [f"- {lab or '(sans nom)'} | calque {ly} | {a:.2f} m²" for a, ly, lab in rooms[:MAX_ROOMS]]
    else:
        out.append("Aucun contour fermé exploitable : surfaces à relever sur les cotes.")
    if wall_len:
        out.append(f"Longueur cumulée de traits sur calques murs/cloisons : {wall_len:.1f} m (traits, pas des linéaires de cloison vérifiés).")
    if dims:
        out.append("Cotes du dessin (m) : " + ", ".join(str(d) for d in sorted(set(dims))[:60]))
    seen = list(dict.fromkeys(t for t, _, _ in texts))[:MAX_TEXTS]
    if seen:
        out.append("Annotations : " + " | ".join(seen))
    return "\n".join(out)


def read_ifc(path: Path) -> str:
    import ifcopenshell
    import ifcopenshell.util.element as el

    model = ifcopenshell.open(str(path))
    out = [f"[CAD IFC] {path.name} — schéma {model.schema}."]

    def qty(obj, *names):
        for pset in (el.get_psets(obj, qtos_only=True) or {}).values():
            for n in names:
                v = pset.get(n)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v)
        return None

    storeys = {s.GlobalId: s.Name or "Niveau" for s in model.by_type("IfcBuildingStorey")}
    spaces = []
    for s in model.by_type("IfcSpace"):
        a = qty(s, "NetFloorArea", "GrossFloorArea", "Area")
        h = qty(s, "Height", "FinishCeilingHeight")
        lvl = ""
        for rel in getattr(s, "Decomposes", None) or []:
            lvl = storeys.get(getattr(rel.RelatingObject, "GlobalId", ""), "")
        spaces.append((s.LongName or s.Name or "Pièce", lvl, a, h))
    if spaces:
        out.append("Pièces (IfcSpace) :")
        out += [f"- {n} | niveau {lvl or '?'} | surface {f'{a:.2f} m²' if a else 'non renseignée'}"
                + (f" | hauteur {h:.2f} m" if h else "") for n, lvl, a, h in spaces[:MAX_ROOMS]]
    else:
        out.append("Aucune pièce (IfcSpace) dans ce modèle : surfaces non disponibles.")
    ceil = [c for c in model.by_type("IfcCovering") if str(getattr(c, "PredefinedType", "") or "").upper() == "CEILING"]
    if ceil:
        total = sum(qty(c, "NetArea", "GrossArea", "Area") or 0 for c in ceil)
        out.append(f"Plafonds (IfcCovering CEILING) : {len(ceil)} élément(s), surface cumulée {total:.2f} m² (0 = non renseignée).")
    walls = model.by_type("IfcWall")
    if walls:
        names = Counter((w.ObjectType or w.Name or "Mur") for w in walls)
        out.append(f"Murs/cloisons : {len(walls)} — " + ", ".join(f"{n} ×{c}" for n, c in names.most_common(15)))
        total = sum(qty(w, "Length") or 0 for w in walls)
        if total:
            out.append(f"Longueur cumulée des murs : {total:.1f} m.")
    out.append("Niveaux : " + (", ".join(storeys.values()) or "non renseignés"))
    return "\n".join(out)
