"""Table ronde : plusieurs experts (appels Claude distincts) examinent le même dossier, DÉBATTENT, puis un arbitre tranche.

Tour 1 : chaque expert donne son avis, seul. Tour 2 : chacun lit les avis des autres, garde, conteste ou corrige, et donne sa
position finale (avant : un seul tour, les experts ne se lisaient jamais). Arbitre (modèle le plus fort) : la MEILLEURE SOLUTION,
pourquoi, les désaccords qui restent (cite qui), les risques et les actions.
Experts choisis selon le problème (placo, argent, droit, vente, autre) ou donnés par l'IA : un problème d'argent n'est plus jugé
par un métreur. Coût : 7 appels (3 avis, 3 répliques, 1 arbitre). L'arbitre signale les désaccords au lieu de les cacher.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from app.config import settings

ROLES = {
    "Métreur": "Tu vérifies les quantités, surfaces, unités, plaques et ossature : refais les calculs, signale toute incohérence ou donnée absente.",
    "Contrôleur": "Tu cherches ce qui peut mal tourner : erreurs, oublis, hypothèses fragiles, risques techniques ou de sécurité, point à faire confirmer sur place.",
    "Commercial": "Tu relis comme le client : clarté, prix cohérents, délais, ce qui manque pour qu'il dise oui, formulation à améliorer.",
}
PANELS = {
    "placo": ROLES,
    "argent": {
        "Financier": "Tu chiffres : trésorerie, marge, coût total, rentabilité ; compare les options avec des chiffres du dossier, jamais inventés.",
        "Contrôleur des risques": "Tu cherches ce qui peut mal tourner : impayé, dette, imprévu, dépendance à un seul client ; ce qu'il faut sécuriser d'abord.",
        "Stratège": "Tu regardes plus loin : l'option qui renforce l'entreprise dans 6 à 12 mois, et les autres voies possibles.",
    },
    "droit": {
        "Juriste": "Tu raisonnes en droit sénégalais (OHADA, Code du travail, contrats) : ce qui protège le patron, les preuves écrites à garder, quand un avocat est indispensable.",
        "Comptable": "Tu vérifies factures, impôts, déclarations et traces écrites : ce qui doit être en règle avant d'agir.",
        "Médiateur": "Tu cherches la sortie la moins coûteuse : solution amiable, relation à préserver, coût réel d'un conflit.",
    },
    "vente": {
        "Commercial": "Tu penses vente : ce qui fait signer le client, le prix juste, l'argument qui manque, la relance.",
        "Marketeur": "Tu penses visibilité : message, réseaux, bouche-à-oreille, image de l'entreprise, ce qui attire les bons clients.",
        "Client exigeant": "Tu es le client difficile : ce qui te ferait hésiter, partir chez un concurrent ou ne pas payer.",
    },
    "general": {
        "Analyste": "Tu décomposes le problème : faits, suppositions, options possibles, ce qui manque pour décider.",
        "Contradicteur": "Tu es l'avocat du diable : attaque la solution évidente, cherche ce qui cloche, propose une autre voie.",
        "Praticien": "Tu es le terrain : ce qui est faisable dès demain avec le temps, l'argent et l'équipe du patron.",
    },
}
# le panel dont les mots reviennent le plus dans le sujet ; à égalité, l'ordre ci-dessous (le métier d'abord)
_PANEL_WORDS = [
    ("placo", r"plafond|cloison|plaque|ba13|placo|ossature|devis|m[ée]tr[ée]|chantier|\bplan\b|rail|montant|fourrure|enduit|peinture"),
    ("argent", r"argent|tr[ée]sorerie|financ|pr[eê]t|banque|cr[ée]dit|invest|rentab|marge|b[ée]n[ée]fice|budget|dette|co[uû]t|\bcaisse\b|[ée]pargne"),
    ("droit", r"contrat|litige|proc[eè]s|avocat|tribunal|juridi|\bloi\b|l[ée]gal|imp[oô]ts?|fisc|licenci|salari[ée]|ohada|huissier|assurance|plainte"),
    ("vente", r"prospect|vente|vendre|march[ée]|publicit|r[ée]seaux|instagram|facebook|tiktok|marketing|concurren|n[ée]goci|fid[ée]li"),
]
RULES = ("Réponds en français, 8 lignes maximum, sans inventer de chiffre ni de fait absent du dossier. "
         "Si le dossier ne permet pas de juger, dis-le. Propose au moins une solution concrète.")
MAX_CONTEXT = 12000


def _ask(system: str, user: str, **kw) -> str:
    from app.ai import ClaudeAIProvider

    res = ClaudeAIProvider().complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=kw.get("max_tokens", 900), model=kw.get("model") or settings.anthropic_fast_model)
    return res.text.strip() if res.available else ""


def panel_for(topic: str, context: str = "", experts: list | None = None) -> tuple[str, dict]:
    """Experts de la table : ceux donnés par l'IA (2 à 4), sinon le panel du sujet."""
    named = [str(e).strip()[:60] for e in (experts or []) if str(e).strip()][:4]
    if len(named) >= 2:
        return "sur mesure", {e: f"Tu examines le problème avec le regard et le savoir de ton métier ({e})." for e in named}
    text = f"{topic} {context}".lower()
    scores = [(len(re.findall(words, text)), -i, name) for i, (name, words) in enumerate(_PANEL_WORDS)]
    best = max(scores)
    return (best[2], PANELS[best[2]]) if best[0] else ("general", PANELS["general"])


def _parallel(jobs: dict) -> dict:
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = {k: pool.submit(_ask, *args) for k, args in jobs.items()}
        return {k: f.result() for k, f in futures.items()}


def run(topic: str, context: str, experts: list | None = None) -> dict:
    topic, context = (topic or "").strip(), (context or "").strip()[:MAX_CONTEXT]
    if not topic:
        return {"error": "Sujet manquant."}
    dossier = f"SUJET : {topic}\n\nDOSSIER :\n{context or '(aucun détail fourni)'}"
    panel, roles = panel_for(topic, context, experts)
    who = {role: f"Tu es {role}, expert{' plaquiste' if panel == 'placo' else ''} à la table ronde du patron d'UniC Plaquiste (Dakar). {brief}"
           for role, brief in roles.items()}
    avis = _parallel({role: (f"{intro} {RULES}", dossier) for role, intro in who.items()})                       # tour 1 : seul
    avis = {r: a for r, a in avis.items() if a}
    if not avis:
        return {"error": "Aucun expert n'a pu répondre (Claude indisponible)."}
    debat: dict = {}
    if len(avis) >= 2:   # tour 2 : chacun lit les autres et répond
        debat = _parallel({role: (
            f"{who[role]} DEUXIÈME TOUR : tu lis les avis des autres experts. Dis ce que tu gardes, ce que tu contestes (cite qui et "
            f"pourquoi), ce que tu corriges dans ton propre avis, puis ta POSITION FINALE en une ligne. {RULES}",
            f"{dossier}\n\nTON AVIS (tour 1) :\n{avis[role]}\n\nAVIS DES AUTRES :\n"
            + "\n\n".join(f"[{r}] {a}" for r, a in avis.items() if r != role)) for role in avis})
        debat = {r: d for r, d in debat.items() if d}
    synth = _ask(
        "Tu es l'arbitre d'une table ronde d'experts. Tu as le dossier, les avis du tour 1 et le débat du tour 2. Rends : "
        "1) MEILLEURE SOLUTION en une ou deux lignes ; 2) Pourquoi (les arguments qui l'emportent) ; 3) Désaccords qui restent (cite qui) ; "
        "4) Risques et points à vérifier ; 5) Actions concrètes, dans l'ordre. Quinze lignes maximum, français, aucune invention. " + RULES,
        dossier + "\n\nAVIS (tour 1) :\n" + "\n\n".join(f"[{r}] {a}" for r, a in avis.items())
        + ("\n\nDÉBAT (tour 2) :\n" + "\n\n".join(f"[{r}] {d}" for r, d in debat.items()) if debat else ""),
        model=settings.anthropic_model, max_tokens=1500)
    return {"avis": avis, "debat": debat, "synthese": synth or "Synthèse indisponible : lis les avis ci-dessus.",
            "experts": list(avis), "panel": panel, "tours": 2 if debat else 1}
