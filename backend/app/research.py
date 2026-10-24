"""Recherche approfondie : une question qui mérite plus qu'une réponse rapide (marché, concurrents, normes, prix publics,
fournisseurs, réglementation, appel d'offres…). Claude cherche longuement sur Internet, croise les sources et rend un rapport
daté et sourcé, rangé en PDF dans les documents.

Garde-fous : chaque affirmation chiffrée renvoie à une source numérotée ; ce qui n'est pas trouvé est dit « non trouvé »,
jamais deviné ; aucune donnée privée de l'entreprise n'est envoyée en recherche ; un rapport sans aucune source est marqué
« non vérifié ». Coût : plusieurs recherches Internet (facturées par Anthropic) + un raisonnement long, compté dans la
consommation comme les autres appels.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

MAX_SEARCHES = 12          # recherches Internet au plus pour un rapport (contre 3 pour une réponse rapide du chat)
MAX_SOURCES = 25
MIN_QUESTION, MAX_QUESTION = 10, 2000

SYSTEM = """Tu es le service de recherche d'UniC Plaquiste (Dakar, Sénégal). Tu rédiges un RAPPORT DE RECHERCHE en français.
Méthode : fais plusieurs recherches Internet variées (mots-clés différents, sources officielles, presse, fournisseurs,
organismes publics) ; croise au moins deux sources pour chaque chiffre important ; privilégie les sources récentes et primaires ;
quand le sujet s'y prête, cherche ce qui vaut AU SÉNÉGAL et en Afrique de l'Ouest (FCFA, normes locales, marché local).
Règles : n'invente RIEN. Chaque chiffre, prix, date ou nom vient d'une source : mets son numéro entre crochets [1].
Ce que tu n'as pas trouvé, écris « non trouvé ». Distingue clairement les faits sourcés, les estimations et les incertitudes.
Indique la date des informations quand elle compte (prix, lois, actualité). Ne demande ni n'utilise aucune donnée privée de l'entreprise.
Format (Markdown simple : « # » pour les titres, « - » pour les listes, **gras**) :
# Réponse courte (3 à 5 lignes)
# Points clés (5 à 8 puces, chacune sourcée)
# Détails
# Ce qui reste incertain ou à vérifier
# Pistes concrètes pour UniC Plaquiste (si le sujet le permet)"""


class ResearchError(Exception):
    pass


def run(db: Session, question: str, user_id: str | None = None) -> dict:
    """Lance la recherche (1 à 3 minutes), compte sa consommation, range le rapport en PDF. Rend le texte, les sources et le PDF."""
    from app import makefiles, usage
    from app.ai import PROVIDERS
    from app.config import settings
    q = " ".join(str(question or "").split())
    if len(q) < MIN_QUESTION:
        raise ResearchError("Précise la question à étudier (au moins une phrase).")
    q = q[:MAX_QUESTION]
    claude = PROVIDERS["claude"]
    if not claude.health().get("available"):
        raise ResearchError("Claude n'est pas configuré : la recherche approfondie a besoin de lui (ANTHROPIC_API_KEY).")
    if not settings.web_search_enabled:
        raise ResearchError("La recherche Internet est coupée dans les réglages du serveur (WEB_SEARCH_ENABLED).")
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    res = claude.complete([{"role": "system", "content": SYSTEM + f"\nDate du jour : {today}."},
                           {"role": "user", "content": f"Question à étudier (donnée du patron) : {q}"}],
                          web=True, web_max_uses=MAX_SEARCHES, sources_raw=True, thinking=True, effort="high",
                          model=settings.anthropic_model, max_tokens=8000)
    try:
        usage.record(db, (res.raw or {}).get("usage"), res.model)
    except Exception:   # noqa: BLE001 — le compteur ne doit jamais faire perdre un rapport
        pass
    if not res.available or not (res.text or "").strip():
        raise ResearchError("La recherche n'a pas abouti (" + (res.error or "réponse vide") + "). Réessaie dans un moment.")
    sources = [s for s in ((res.raw or {}).get("sources") or []) if s.get("url")][:MAX_SOURCES]
    body = res.text.strip()
    if not sources:
        body = ("**ATTENTION : aucune source Internet n'a été retrouvée pour ce rapport. Il n'est pas vérifié : "
                "ne t'en sers pas pour un prix, une loi ou une décision.**\n\n" + body)
    else:
        body += "\n\n# Sources\n" + "\n".join(f"- [{i}] {s.get('title') or s['url']} — {s['url']}" for i, s in enumerate(sources, 1))
    body += f"\n\nRecherche faite le {today} par UniC AI. Les informations d'Internet peuvent changer : vérifie avant une décision importante."
    art = makefiles.make_pdf(db, f"Recherche — {q[:80]}", body[:makefiles.MAX_PDF_CHARS], user_id)
    db.commit()
    if sources:   # le savoir sourcé reste : une question future sur le même sujet le retrouve (library)
        try:
            from app import library
            library.save(db, f"Recherche — {q[:120]}", body, "recherche approfondie, sources listées dans le texte", user_id)
        except Exception:   # noqa: BLE001 — ranger le savoir ne doit jamais faire perdre le rapport
            db.rollback()
    return {"rapport": body, "sources": sources, "verifie": bool(sources), "artifact": art}
