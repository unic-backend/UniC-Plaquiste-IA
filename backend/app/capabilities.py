"""Registre central des capacités UniC AI. Chaque capacité a un schéma, une santé, une exécution réelle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app import ocr
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


def _connectors():
    email_ok = bool(settings.smtp_host and settings.smtp_user)
    return {
        "email": email_ok,
        "website": False,
        "social": False,
        "gbp": False,
        "ocr": ocr.disponible(),
        "voice_server": False,
    }


def registry_snapshot() -> list[dict]:
    conn = _connectors()
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
        Capability("read_email", "Lire la messagerie connectée",
                   {}, {}, ["user"], conn["email"],
                   "" if conn["email"] else "NON DISPONIBLE — connecteur e-mail non configuré."),
        Capability("create_social_post", "Préparer un post réseaux (brouillon)",
                   {"text": "str"}, {"draft": "object"}, ["manager"], True),
        Capability("publish_social_post", "Publier sur les réseaux officiels",
                   {"post_id": "str"}, {}, ["admin"], False,
                   "NON DISPONIBLE — aucun connecteur social configuré."),
        Capability("manage_google_business", "Google Business Profile",
                   {}, {}, ["admin"], False,
                   "NON DISPONIBLE — API Google Business non configurée."),
        Capability("website_update", "Préparer une mise à jour du site UniC",
                   {"content": "str"}, {"draft": "object"}, ["admin"], False,
                   "NON DISPONIBLE — connecteur site non configuré. La préparation de texte reste possible."),
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


def health_dashboard() -> dict:
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
        "capabilities": registry_snapshot(),
        "connectors": {
            "email": "ok" if settings.smtp_host else "not_configured",
            "website": "not_configured",
            "social": "not_configured",
            "google_business": "not_configured",
            "ocr": "not_configured",
        },
        "note": "Le serveur cloud UniC AI fonctionne même si le PC personnel est éteint.",
    }
