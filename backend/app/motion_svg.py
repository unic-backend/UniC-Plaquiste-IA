"""Animations libres dessinées par l'IA du Studio (scène « motion ») : un SVG animé en CSS (@keyframes), nettoyé ICI avant le moteur.

L'IA n'est plus limitée à une liste d'effets : elle compose l'image que la vidéo demande (interface, objet, schéma, décor, personnage
stylisé…). Ce qu'elle écrit est une donnée : seules des balises de dessin sont gardées ; aucun script, aucun gestionnaire d'événement,
aucune ressource externe (lien, image, police, @import), aucun objet étranger. Fonction pure, sans base ni réseau.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
MAX_CHARS = 60_000          # un dessin, pas un film : au-delà, la scène est refusée
MAX_NODES = 1500
TAGS = {"svg", "g", "defs", "style", "title", "desc", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan",
        "textPath", "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern", "symbol", "use", "marker", "filter",
        "feGaussianBlur", "feOffset", "feMerge", "feMergeNode", "feColorMatrix", "feBlend", "feFlood", "feComposite", "feMorphology",
        "feTurbulence", "feDisplacementMap", "feDropShadow", "feComponentTransfer", "feFuncA", "feFuncR", "feFuncG", "feFuncB"}
BAD_CSS = re.compile(r"@import|@font-face|@namespace|expression\s*\(|javascript:|behavior\s*:|-moz-binding|\\|</|<!--|url\s*\(\s*['\"]?\s*(?!#)", re.I)
BAD_VALUE = re.compile(r"javascript:|data:|vbscript:|url\s*\(\s*['\"]?\s*(?!#)", re.I)
DIMS = {"vertical": (1080, 1920), "horizontal": (1920, 1080), "square": (1080, 1080)}

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _ok_href(v: str) -> bool:
    return bool(re.fullmatch(r"#[A-Za-z_][\w.-]{0,80}", v.strip()))


def clean(svg, fmt: str = "vertical") -> str | None:
    """SVG de l'IA -> SVG sûr (balises de dessin, styles CSS sans ressource externe), cadré au format ; None si illisible ou dangereux."""
    if not isinstance(svg, str):
        return None
    src = svg.strip()
    if not src or len(src) > MAX_CHARS or re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", src, re.I):
        return None
    if "xmlns=" not in src[:400]:
        src = re.sub(r"^<svg\b", f'<svg xmlns="{SVG_NS}"', src, count=1)
    try:
        root = ET.fromstring(src)
    except ET.ParseError:
        return None
    if _local(root.tag) != "svg":
        return None
    nodes = 0

    def walk(el: ET.Element) -> bool:
        nonlocal nodes
        for child in list(el):
            nodes += 1
            if nodes > MAX_NODES:
                return False
            if not isinstance(child.tag, str) or _local(child.tag) not in TAGS or not child.tag.startswith("{" + SVG_NS):
                el.remove(child)      # balise inconnue ou étrangère (script, foreignObject, image, a, iframe…) : retirée avec son contenu
                continue
            if _local(child.tag) == "style" and BAD_CSS.search(child.text or ""):
                el.remove(child)
                continue
            if not attrs(child) or not walk(child):
                return False
        return True

    def attrs(el: ET.Element) -> bool:
        for k in list(el.attrib):
            name, v = _local(k), el.attrib[k]
            if name.lower().startswith("on"):
                del el.attrib[k]
            elif name == "href":
                if not _ok_href(v):
                    del el.attrib[k]
            elif name == "style" and BAD_CSS.search(v):
                del el.attrib[k]
            elif BAD_VALUE.search(v):
                del el.attrib[k]
        return True

    if not attrs(root) or not walk(root):
        return None
    w, h = DIMS.get(fmt, DIMS["vertical"])
    if "viewBox" not in root.attrib:
        root.set("viewBox", f"0 0 {w} {h}")
    root.set("width", "100%")
    root.set("height", "100%")
    root.set("preserveAspectRatio", "xMidYMid slice")
    out = ET.tostring(root, encoding="unicode")
    return out if len(out) <= MAX_CHARS else None
