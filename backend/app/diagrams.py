"""Schémas dessinés en code : Claude écrit du SVG, le serveur le nettoie puis le convertit en PNG partageable.

Jamais une photo : plans de pièce, coupes de plafond, schémas de cloison, graphiques, logos simples.
Le SVG de l'IA est une donnée non fiable : liste blanche de balises et d'attributs, aucune référence externe.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Artifact, new_id
from app.services import store_artifact

MAX_SVG = 120_000
SVG_NS = "http://www.w3.org/2000/svg"
TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "defs", "title", "desc",
        "lineargradient", "radialgradient", "stop", "marker", "clippath"}
BAD_VALUE = re.compile(r"url\s*\(\s*['\"]?\s*(?!#)|@import|javascript:|expression\s*\(|data:|https?:", re.I)


class DiagramError(Exception):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def sanitize(svg: str) -> str:
    """SVG propre ou DiagramError. Refuse DOCTYPE/ENTITY (bombes XML), scripts, images et liens externes."""
    svg = (svg or "").strip()
    if not svg or len(svg) > MAX_SVG:
        raise DiagramError("SVG vide ou trop volumineux.")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", svg, re.I):
        raise DiagramError("SVG refusé (déclarations non autorisées).")
    try:
        root = ET.fromstring(svg)  # nosec B314 - DOCTYPE/ENTITY refusés plus haut
    except ET.ParseError as exc:
        raise DiagramError(f"SVG invalide : {exc}") from exc
    if _local(root.tag) != "svg":
        raise DiagramError("La racine doit être <svg>.")

    def clean(el: ET.Element) -> None:
        for child in list(el):
            if _local(child.tag) not in TAGS:
                el.remove(child)   # script, image, foreignObject, use, style… supprimés
            else:
                clean(child)
        for name in list(el.attrib):
            low, val = _local(name), el.attrib[name]
            if low.startswith("on") or low in ("href", "src") or BAD_VALUE.search(val):
                del el.attrib[name]

    clean(root)
    root.set("xmlns", SVG_NS) if "}" not in root.tag else None
    if not root.get("viewBox") and not (root.get("width") and root.get("height")):
        raise DiagramError("Le SVG doit avoir un viewBox (ex. viewBox=\"0 0 800 600\").")
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode")


def render(db: Session, title: str, svg: str, user_id: str | None) -> Artifact:
    try:
        import cairosvg
    except Exception as exc:   # bibliothèque système absente
        raise DiagramError("Dessin indisponible : moteur de rendu non installé sur le serveur.") from exc
    safe = sanitize(svg)
    key = new_id()[:8]
    name = re.sub(r"[^\w\-]+", "_", title or "schema").strip("_")[:40] or "schema"
    folder = settings.artifacts_path / "diagrams"
    folder.mkdir(parents=True, exist_ok=True)
    png = folder / f"UniC_{name}_{key}.png"
    try:
        cairosvg.svg2png(bytestring=safe.encode("utf-8"), write_to=str(png), output_width=1600, background_color="white")
    except Exception as exc:
        raise DiagramError("Dessin impossible : SVG non exploitable.") from exc
    (folder / f"UniC_{name}_{key}.svg").write_text(safe, encoding="utf-8")
    return store_artifact(db, png, png.name, "diagram", key, f"unic-diagram-{key}", user_id, mime="image/png")
