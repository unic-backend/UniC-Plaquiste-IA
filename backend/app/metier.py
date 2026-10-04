"""Connaissances métier UniC (prix, ratios, conventions) venues des documents réels du propriétaire.

Source : app/data/metier_unic.json. Un article absent de la grille n'a pas de prix :
l'assistant le dit, il n'en invente pas. L'import ne remplace JAMAIS ce que le
propriétaire a déjà saisi.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app import calc
from app.models import CompanySettings, KnowledgeArticle, Material, MaterialPrice, Service, SocialAccount

# Dossier nommé « metier_data » (pas « data ») : .gitignore et .dockerignore excluent « data/ ».
DATA = Path(__file__).parent / "metier_data" / "metier_unic.json"
PRICE_SOURCE = "Devis Fast Group 14/07 et 04/08/2026 (grille propriétaire)"
PRECISION = 6

# Articles dont l'unité commerciale = l'unité du catalogue UniC : le prix s'applique tel quel.
EXISTING_SKU = {
    "Plaque standard BA13": "BA13-2500x1200",
    "Plaque hydrofuge": "BA13-2500x1200-H",
    "Plaque BA13 standard 2 m": "BA13-2000x1200",
    "Plaque BA13 hydrofuge 2 m": "BA13-2000x1200-H",
    "Montant 48 mm": "MONTANT-M48",
    "Montant 7 cm (70 mm)": "MONTANT-M70",
}
LABOR_SKU = "UC-MAIN-OEUVRE-M2"


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _slug(label: str) -> str:
    base = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().upper()
    return "UC-" + re.sub(r"[^A-Z0-9]+", "-", base).strip("-")[:56]


def sku_for(article: str) -> str:
    return EXISTING_SKU.get(article) or _slug(article)


def _unit(article: str) -> str:
    low = article.lower()
    for word, unit in (("barre", "barre"), ("paquet", "paquet"), ("sac", "sac"), ("seau", "seau"), ("feuille", "feuille"),
                       ("planche", "planche"), ("rails", "barre"), ("tiges", "u")):
        if word in low:
            return unit
    return "u"


def _category(article: str) -> str:
    low = article.lower()
    if "plaque" in low:
        return "plaques"
    if any(w in low for w in ("rail", "montant", "corni", "fourrure")):
        return "ossature"
    if any(w in low for w in ("enduit", "bande", "toile", "papier", "katex", "ciment")):
        return "finition"
    if "peinture" in low:
        return "peinture"
    if any(w in low for w in ("contreplaqu", "planche", "quincaillerie")):
        return "portes"
    return "fixation"


def import_metier(db: Session) -> dict:
    """Importe société, profils, prix, connaissances. Additif et idempotent."""
    m = load()
    added = {"materials": 0, "prices": 0, "articles": 0, "profiles": 0}

    # --- société : seulement les champs vides
    ent = m["entreprise"]
    co = db.query(CompanySettings).first()
    if co is None:
        co = CompanySettings(name=ent["nom"])
        db.add(co)
    fill = {"phone": ent.get("telephone"), "email": ent.get("email"), "website": ent.get("site"),
            "tax_id": ent.get("ninea"), "currency": ent.get("devise"), "city": "Dakar", "country": "Sénégal",
            "address": ent.get("adresse")}
    for field, value in fill.items():
        if value and not getattr(co, field):
            setattr(co, field, value)
    if not co.notes:
        co.notes = f"RCCM : {ent.get('rccm', '')}. Gérant : {ent.get('gerant', '')}. {ent.get('specialite', '')}."

    # --- profils réseaux (profil noté, pas une connexion API)
    profiles = {"instagram": ("@unic_plaquiste", ent["reseaux_sociaux"].get("instagram", "")),
                "tiktok": ("@unic_plaquiste", ent["reseaux_sociaux"].get("tiktok", "")),
                "google_business": ("UniC Plaquiste", ent.get("fiche_google_maps", "")),
                "website": (ent.get("site", ""), "https://" + ent["site"] if ent.get("site") else "")}
    for platform, (handle, url) in profiles.items():
        if url and db.query(SocialAccount).filter(SocialAccount.platform == platform).first() is None:
            db.add(SocialAccount(platform=platform, handle=handle, page_url=url, linked=True))
            added["profiles"] += 1

    # --- matériaux + prix de vente
    cur = ent.get("devise", "")
    grid = {**m.get("prix_materiaux", {}), **m.get("prix_portes", {})}
    for article, price in grid.items():
        sku = sku_for(article)
        mat = db.query(Material).filter(Material.sku == sku).first()
        if mat is None:
            mat = Material(sku=sku, name=article, category=_category(article), unit=_unit(article),
                           waste_coefficient=0.0, availability="unknown",
                           notes="Article de la grille UniC (unité commerciale).")
            db.add(mat)
            db.flush()
            added["materials"] += 1
        if db.query(MaterialPrice).filter(MaterialPrice.material_id == mat.id, MaterialPrice.kind == "selling").first() is None:
            db.add(MaterialPrice(material_id=mat.id, kind="selling", amount=float(price), currency=cur,
                                 source=PRICE_SOURCE, notes="À revérifier : prix de juillet-août 2026."))
            added["prices"] += 1

    labor = m.get("main_oeuvre", {})
    if labor.get("tarif_m2"):
        mat = db.query(Material).filter(Material.sku == LABOR_SKU).first()
        if mat is None:
            mat = Material(sku=LABOR_SKU, name="Main-d'œuvre — pose complète", category="main_oeuvre", unit="m²",
                           waste_coefficient=0.0, notes=labor.get("libelle", ""))
            db.add(mat)
            db.flush()
            added["materials"] += 1
        if db.query(MaterialPrice).filter(MaterialPrice.material_id == mat.id, MaterialPrice.kind == "selling").first() is None:
            db.add(MaterialPrice(material_id=mat.id, kind="selling", amount=float(labor["tarif_m2"]), currency=cur,
                                 source=PRICE_SOURCE, notes="Par m² de surface développée."))
            added["prices"] += 1
        svc = db.query(Service).filter(Service.code == "POSE").first()
        if svc is not None and svc.selling_price is None:
            svc.selling_price = float(labor["tarif_m2"])
            svc.unit = "m²"
            svc.notes = "Forfait pose complète UniC, par m² développé (devis Fast Group 2026)."

    # --- connaissances
    for slug, title, cat, body in _articles(m):
        if db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == slug).first() is None:
            db.add(KnowledgeArticle(slug=slug, title=title, category=cat, body=body))
            added["articles"] += 1
    db.commit()
    return added


def _articles(m: dict) -> list[tuple[str, str, str, str]]:
    conv, ratios = m["conventions"], m["ratios_materiaux"]
    rules = [
        f"Surface développée : {conv['regle_surface'].strip()}",
        f"Numérotation des documents : {conv['numerotation']} (CLI = initiales du client).",
        f"Validité d'un devis : {conv['validite_devis_jours'][0]} à {conv['validite_devis_jours'][1]} jours.",
        conv["mention_prix_unitaire"].strip(),
    ]
    return [
        ("unic-regles-devis", "Règles de devis UniC", "company", "\n\n".join(rules)),
        ("unic-exclusions", "Exclusions et métiers hors périmètre", "company",
         "Exclusions habituelles des devis :\n" + "\n".join(f"- {e}" for e in m["exclusions_habituelles"])
         + "\n\nMétiers qui ne sont pas ceux d'UniC (jamais chiffrés, renvoyer vers un corps de métier) : "
         + ", ".join(m["metiers_hors_perimetre"]) + "."),
        ("unic-engagements", "Ton et engagements de la maison", "company",
         "\n\n".join(m["engagements"].values())),
        ("unic-ratios", "Ratios matériaux de référence (chantier réel)", "procedure",
         f"Source : {ratios['source']}. Limite : un seul chantier (montants 70 mm + laine de verre) ; "
         "un chantier en 48 mm sans isolation consommera autrement.\n"
         "Suivent la surface développée (quantités pour "
         f"{ratios['reference_m2_developpe']:g} m²) : "
         + "; ".join(f"{k} {v}" for k, v in ratios["suivent_la_surface"].items())
         + ".\nUn par paroi : " + ", ".join(ratios["par_paroi"]) + "."),
    ]


# ---------- calcul « méthode UniC » (ratios du chantier de référence) ----------

def _up(value: float) -> int:
    return int(math.ceil(round(value, PRECISION)))


def calculate_unic(surface: float, faces: int = 2, parois: int | None = None,
                   already_developed: bool = False) -> calc.CalcResult:
    """Matériaux d'un chantier selon les ratios réels du propriétaire. Quantités arrondies au-dessus."""
    if surface is None or surface <= 0:
        raise ValueError("La surface doit être strictement positive.")
    if faces not in (1, 2):
        raise ValueError("1 face (doublage) ou 2 faces (cloison fermée).")
    m = load()
    ratios = m["ratios_materiaux"]
    ref = float(ratios["reference_m2_developpe"])
    ref_wall = float(ratios["paroi_reference_m2_developpe"])
    dev = float(surface) if already_developed else float(surface) * faces
    estimated = parois is None
    walls = parois if parois else _up(dev / ref_wall)

    if already_developed:
        convention = f"Hypothèse : les {surface:g} m² annoncés sont déjà développés."
    else:
        convention = (f"Hypothèse : {surface:g} m² de mur sur {faces} face(s) — {surface:g} × {faces} = {dev:g} m² développés. "
                      f"Si {surface:g} m² étaient déjà développés, le résultat serait divisé par {faces}.")

    res = calc.CalcResult(kind="partition_unic", title="Matériaux — méthode UniC (ratios du propriétaire)",
                          understanding=convention, inputs={"surface": surface, "faces": faces, "parois": walls})
    res.steps = [calc.CalcStep("Surface développée", "surface × faces" if not already_developed else "valeur saisie",
                               {"S": surface, "faces": faces}, dev, "m²")]
    lines: list[calc.QuantityLine] = []
    for article, qty_ref in ratios["suivent_la_surface"].items():
        exact = qty_ref * dev / ref
        lines.append(calc.QuantityLine(sku_for(article), article, _up(exact), _unit(article),
                                       f"⌈{qty_ref} × {dev:g} / {ref:g}⌉", calc.STATUS_ESTIMATED))
    for article, per in ratios["par_paroi"].items():
        lines.append(calc.QuantityLine(sku_for(article), article, _up(per * walls), _unit(article),
                                       f"{per} × {walls} paroi(s)", calc.STATUS_ESTIMATED))
    labor = m.get("main_oeuvre", {})
    if labor.get("tarif_m2"):
        lines.append(calc.QuantityLine(LABOR_SKU, "Main-d'œuvre — pose complète", round(dev, 2), "m²",
                                       f"{dev:g} m² développés", calc.STATUS_ESTIMATED))
    res.quantities = lines
    res.assumptions = [
        convention,
        f"Ratios issus de : {ratios['source']}.",
        "Limite : un seul chantier (montants 70 mm + laine de verre). Un autre type de paroi consomme autrement.",
    ]
    if estimated:
        res.assumptions.append(f"Nombre de parois non donné : estimé à {walls} sur la base d'une paroi de référence de {ref_wall:g} m² développés.")
    res.missing = ["Transport / livraison : non chiffré.", *[f"Exclu : {e}" for e in m["exclusions_habituelles"][:2]]]
    return res


UNIC_METHOD_RE = re.compile(r"m[ée]thode unic|ratios? unic|chiffrage unic|calcul unic|comme (?:pour )?fast ?group|devis unic", re.I)


def calculate_unic_from_text(text: str) -> calc.CalcResult | None:
    """Lit surface / faces / parois dans la phrase. None si la surface est introuvable."""
    t = text.lower().replace("×", "x")
    surface = None
    am = re.search(rf"({calc._NUM})\s*(?:m²|m2)", t)
    if am:
        surface = calc.parse_number(am.group(1))
    else:
        pair = calc._extract_dimension_pair(t)
        if pair:
            surface = pair[0] * pair[1]
    if not surface:
        return None
    pm = re.search(r"(\d+)\s*parois?", t)
    return calculate_unic(surface, faces=calc._sides(t), parois=int(pm.group(1)) if pm else None,
                          already_developed=bool(re.search(r"d[ée]j[àa] d[ée]velopp", t)))
