"""Table ronde : plusieurs experts (appels Claude distincts) examinent le même dossier, puis un arbitre tranche.

Pour les travaux qui se contrôlent à plusieurs regards (devis important, plan ambigu, décision à enjeu).
Coût : 4 appels au modèle rapide. L'arbitre signale les désaccords au lieu de les cacher.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.config import settings

ROLES = {
    "Métreur": "Tu vérifies les quantités, surfaces, unités, plaques et ossature : refais les calculs, signale toute incohérence ou donnée absente.",
    "Contrôleur": "Tu cherches ce qui peut mal tourner : erreurs, oublis, hypothèses fragiles, risques techniques ou de sécurité, point à faire confirmer sur place.",
    "Commercial": "Tu relis comme le client : clarté, prix cohérents, délais, ce qui manque pour qu'il dise oui, formulation à améliorer.",
}
RULES = ("Réponds en français, 6 lignes maximum, sans inventer de chiffre ni de fait absent du dossier. "
         "Si le dossier ne permet pas de juger, dis-le.")
MAX_CONTEXT = 12000


def _ask(system: str, user: str) -> str:
    from app.ai import ClaudeAIProvider

    res = ClaudeAIProvider().complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=900, model=settings.anthropic_fast_model)
    return res.text.strip() if res.available else ""


def run(topic: str, context: str) -> dict:
    topic, context = (topic or "").strip(), (context or "").strip()[:MAX_CONTEXT]
    if not topic:
        return {"error": "Sujet manquant."}
    dossier = f"SUJET : {topic}\n\nDOSSIER :\n{context or '(aucun détail fourni)'}"
    with ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
        futures = {role: pool.submit(_ask, f"Tu es {role}, expert plaquiste. {brief} {RULES}", dossier) for role, brief in ROLES.items()}
        avis = {role: f.result() for role, f in futures.items()}
    avis = {r: a for r, a in avis.items() if a}
    if not avis:
        return {"error": "Aucun expert n'a pu répondre (Claude indisponible)."}
    synth = _ask(
        "Tu es l'arbitre d'une table ronde. Rends : 1) Verdict en une ligne ; 2) Points d'accord ; 3) Désaccords ou doutes (cite qui) ; "
        "4) Actions avant d'envoyer. Dix lignes maximum, français, aucune invention. " + RULES,
        dossier + "\n\nAVIS DES EXPERTS :\n" + "\n\n".join(f"[{r}] {a}" for r, a in avis.items()))
    return {"avis": avis, "synthese": synth or "Synthèse indisponible : lis les avis ci-dessus.", "experts": list(avis)}
