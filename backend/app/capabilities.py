"""Registre central des capacités UniC AI. Chaque capacité a un schéma, une santé, une exécution réelle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app import google_business, instagram, linkedin, mailbox, ocr, vision, voice, website
from app.config import settings
from app.ai import providers_health


@dataclass
class Capability:
    id: str
    description: str
    input_schema: dict
    output_schema: dict
    permissions: list[str]
    available: bool
    reason: str = ""
    handler: Callable | None = field(default=None, repr=False)


def _connectors(db=None) -> dict:
    """État RÉEL des connecteurs (jamais une valeur figée). Sans base : on ne présume pas qu'ils sont branchés."""
    conn = {"email": mailbox.imap_configured(), "website": False, "linkedin": False, "instagram": False, "gbp": google_business.configured(),
            "ocr": ocr.disponible(), "vision": vision.disponible(), "voice": False}
    if db is not None:
        for key, fn in (("website", website.status), ("linkedin", linkedin.status), ("instagram", instagram.status)):
            try:
                conn[key] = bool(fn(db).get("connected"))
            except Exception:
                conn[key] = False
        try:
            conn["voice"] = bool(voice.status(db).get("configured"))
        except Exception:
            pass
    conn["social"] = conn["linkedin"] or conn["instagram"]
    return conn


def registry_snapshot(db=None) -> list[dict]:
    conn = _connectors(db)
    caps = [
        Capability("read_pdf", "Lire un PDF et extraire le texte page par page",
                   {"file_id": "str"}, {"pages": "int", "status": "str"}, ["user"], True),
        Capability("analyze_large_pdf", "Indexer un PDF volumineux et rechercher par page",
                   {"file_id": "str", "query": "str"}, {"hits": "list"}, ["user"], True),
        Capability("ocr_document", "OCR de documents scannés",
                   {"file_id": "str"}, {"text": "str"}, ["user"], ocr.disponible(),
                   "" if ocr.disponible() else "NON DISPONIBLE — Tesseract n'est pas installé sur ce serveur."),
        Capability("analyze_architectural_plan", "Rechercher portes, cloisons, cotes dans un plan",
                   {"file_id": "str", "topic": "str"}, {"hits": "list"}, ["user"], True),
        Capability("analyze_site_photo", "Stocker une photo de chantier (vision si IA cloud)",
                   {"file_id": "str"}, {"status": "str"}, ["user"], True),
        Capability("calculate_surface", "Calculer une surface",
                   {"length": "float", "width": "float"}, {"area": "float"}, ["user"], True),
        Capability("calculate_materials", "Calculer plaques, ossature, finitions",
                   {"length": "float", "height": "float"}, {"quantities": "list"}, ["user"], True),
        Capability("calculate_quantity_takeoff", "Métré à partir d'un texte ou d'un calcul",
                   {"text": "str"}, {"quantities": "list"}, ["user"], True),
        Capability("calculate_price", "Appliquer uniquement les prix UniC saisis",
                   {"sku": "str"}, {"price": "float|null"}, ["user"], True),
        Capability("create_quote", "Créer un devis et générer un PDF réel",
                   {"quantities": "list"}, {"quotation": "object"}, ["manager", "admin"], True),
        Capability("generate_quote_pdf", "Régénérer le PDF d'un devis",
                   {"quotation_id": "str"}, {"artifact": "object"}, ["manager", "admin"], True),
        Capability("create_invoice", "Créer une facture (ou à partir d'un devis)",
                   {"quotation_id": "str"}, {"invoice": "object"}, ["manager", "admin"], True),
        Capability("generate_invoice_pdf", "Régénérer le PDF d'une facture",
                   {"invoice_id": "str"}, {"artifact": "object"}, ["manager", "admin"], True),
        Capability("create_purchase_order", "Créer un bon de commande PDF",
                   {"quantities": "list"}, {"order": "object"}, ["manager", "admin"], True),
        Capability("create_delivery_note", "Créer un bon de livraison PDF",
                   {"quantities": "list"}, {"note": "object"}, ["manager", "admin"], True),
        Capability("create_site_report", "Créer un rapport de chantier PDF",
                   {"notes": "list"}, {"artifact": "object"}, ["user"], True),
        Capability("manage_project", "Créer / consulter projets et chantiers",
                   {"name": "str"}, {"project": "object"}, ["user"], True),
        Capability("search_company_knowledge", "Interroger la base de connaissance UniC",
                   {"query": "str"}, {"articles": "list"}, ["user"], True),
        Capability("draft_email", "Rédiger un brouillon d'e-mail (sans envoi auto)",
                   {"to": "str", "subject": "str"}, {"draft": "object"}, ["user"], True),
        Capability("read_email", "Lire la boîte mail (IMAP), résumer, proposer des réponses",
                   {}, {}, ["user"], conn["email"],
                   "" if conn["email"] else "NON DISPONIBLE — Gmail non connecté (Paramètres › Courrier)."),
        Capability("create_social_post", "Préparer posts et réponses (11 plateformes, brouillon → revue → approbation)",
                   {"text": "str"}, {"draft": "object"}, ["manager"], True),
        Capability("publish_social_post", "Publier sur LinkedIn (après ton approbation)",
                   {"post_id": "str"}, {}, ["admin"], conn["linkedin"],
                   "" if conn["linkedin"] else "NON DISPONIBLE — LinkedIn non connecté (Réseaux › LinkedIn). Autres réseaux : publication manuelle."),
        Capability("manage_google_business", "Fiche Google : publier / répondre aux avis via API",
                   {}, {}, ["admin"], conn["gbp"],
                   "" if conn["gbp"] else "NON DISPONIBLE — accès API Google en attente d'approbation. Brouillons seulement."),
        Capability("website_update", "Préparer une page du site (brouillon, jamais publiée sans ton clic)",
                   {"content": "str"}, {"draft": "object"}, ["admin"], conn["website"],
                   "" if conn["website"] else "NON DISPONIBLE — site non connecté (Réseaux › Site web)."),
        Capability("read_plan", "Lire un plan : pièces, surfaces, plafonds, références placo/cloisons (FR/EN)",
                   {"file_id": "str"}, {"pieces": "list"}, ["user"], vision.disponible(),
                   "" if vision.disponible() else "NON DISPONIBLE — clé Claude absente."),
        Capability("read_cad", "Lire DXF et IFC (AutoCAD, Revit, ArchiCAD)",
                   {"file_id": "str"}, {"text": "str"}, ["user"], True),
        Capability("read_image", "Regarder photos, plans scannés et PDF sans texte (vision Claude)",
                   {"file_id": "str"}, {"text": "str"}, ["user"], vision.disponible(),
                   "" if vision.disponible() else "NON DISPONIBLE — clé Claude absente."),
        Capability("draw_diagram", "Dessiner un schéma, un graphique ou un logo en SVG → PNG partageable",
                   {"svg": "str"}, {"image": "object"}, ["user"], True),
        Capability("design_logo", "Concevoir et auditer des logos (méthode d'identité, 3 concepts)",
                   {"brief": "str"}, {"concepts": "list"}, ["user"], True),
        Capability("learned_knowledge", "Réponses validées (Retenir) réutilisées quand Claude est indisponible",
                   {"question": "str"}, {"answer": "str"}, ["user"], True),
        Capability("voice", "Lecture vocale des réponses (ElevenLabs)",
                   {"text": "str"}, {"audio": "bytes"}, ["user"], conn["voice"],
                   "" if conn["voice"] else "NON DISPONIBLE — clé ElevenLabs non enregistrée (voix du téléphone en secours)."),
    ]
    return [
        {
            "id": c.id,
            "description": c.description,
            "input_schema": c.input_schema,
            "output_schema": c.output_schema,
            "permissions": c.permissions,
            "available": c.available,
            "reason": c.reason,
            "health": "ok" if c.available else "not_available",
        }
        for c in caps
    ]


def memory_mb() -> dict:
    """Mémoire du serveur (actuelle et pic) : permet de voir si Render (512 Mo) approche de sa limite."""
    out = {}
    try:
        for line in open("/proc/self/status"):
            if line.startswith(("VmRSS", "VmHWM")):
                out["actuelle_mo" if line.startswith("VmRSS") else "pic_mo"] = int(line.split()[1]) // 1024
    except OSError:
        pass
    return out


def release_memory() -> None:
    """Rend au système la mémoire libérée après un gros travail (fichier, réponse longue) : le serveur ne gonfle pas au fil des envois."""
    import ctypes
    import gc

    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:   # hors Linux/glibc : sans effet
        pass


def health_dashboard(db=None) -> dict:
    from app.database import engine
    db_ok = True
    db_detail = "ok"
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:
        db_ok = False
        db_detail = str(exc)
    storage_ok = settings.storage_path.exists()
    return {
        "app": "UniC AI",
        "status": "ok" if db_ok and storage_ok else "degraded",
        "database": {"status": "ok" if db_ok else "error", "detail": db_detail, "url_kind": "sqlite" if settings.is_sqlite else "external"},
        "storage": {"status": "ok" if storage_ok else "error", "path": str(settings.storage_path)},
        "ai_providers": providers_health(),
        "memory": memory_mb(),
        "capabilities": registry_snapshot(db),
        "connectors": {k: ("ok" if v else "not_configured") for k, v in _connectors(db).items()},
        "note": "Le serveur cloud UniC AI fonctionne même si le PC personnel est éteint.",
    }
