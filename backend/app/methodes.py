"""Méthodes métier (idée reprise de claude-skills / pm-skills, écrites pour UniC) : quand le patron demande une stratégie, un plan
ou une décision, l'IA suit une méthode éprouvée au lieu d'improviser. Seule la liste courte est dans la description de l'outil ;
la méthode complète n'est chargée qu'à la demande (économie de tokens).

Règle commune : les chiffres de l'entreprise (prix, coûts, CA, clients) viennent des outils et du patron, jamais de l'IA.
"""
from __future__ import annotations

REGLES = ("Chiffres de l'entreprise : seulement ceux des outils (get_prices, business_report, cash_forecast, list_unpaid…) ou du patron ; "
          "un chiffre manquant se demande, il ne s'invente pas. Faits extérieurs (marché, concurrents, normes) : deep_research ou "
          "recherche Internet, avec la source. Réponse courte : le résultat d'abord, puis « Je détaille ? ».")

METHODES: dict[str, dict] = {
    "plan_marketing": {
        "titre": "Plan marketing local (30 jours)",
        "quand": "trouver plus de clients, se faire connaître, plan de communication",
        "etapes": [
            "Cible : 1 ou 2 clients types (particulier qui rénove, promoteur, architecte, entreprise générale) et leur besoin principal.",
            "Offre : ce qui rend UniC différent pour cette cible (délai, finition, garantie, conseil), en une phrase.",
            "Canaux : fiche Google (avis, photos, publications), WhatsApp Business, Facebook/Instagram/TikTok (avant/après), "
            "bouche-à-oreille et apporteurs (architectes, quincailleries), chantiers visibles (panneau).",
            "Calendrier 30 jours : 3 actions par semaine, chacune avec qui, quand, et ce qu'on mesure.",
            "Mesure : demandes reçues, devis envoyés, devis signés, d'où vient chaque client.",
        ],
        "rendu": "Tableau semaine → actions → mesure ; budget seulement si le patron le donne.",
    },
    "prix": {
        "titre": "Fixer ou vérifier un prix",
        "quand": "combien facturer, prix trop bas ou trop haut, remise demandée, nouveau service",
        "etapes": [
            "Coût de revient réel : matériaux (prix du patron via get_prices), main-d'œuvre, transport, chutes, outillage.",
            "Marge visée : celle du patron (la demander si inconnue).",
            "Prix du marché : seulement s'il est sourcé (recherche) ; sinon le dire.",
            "Remise : jamais sous le coût de revient ; contrepartie demandée (acompte plus élevé, volume, délai souple).",
            "Décision : prix proposé, marge obtenue, et le risque principal.",
        ],
        "rendu": "Formule sur une ligne : coût + marge = prix ; puis la recommandation en gras.",
    },
    "croissance": {
        "titre": "Trouver ce qui freine la croissance",
        "quand": "le chiffre stagne, pourquoi on ne grandit pas, quoi améliorer en premier",
        "etapes": [
            "Entonnoir sur les vrais chiffres : demandes → visites/métrés → devis envoyés → devis signés → chantiers payés → clients qui reviennent ou recommandent.",
            "Le maillon le plus faible (taux le plus bas ou délai le plus long).",
            "3 actions sur ce seul maillon, de la plus simple à la plus forte.",
            "Ce qu'on mesure dans 30 jours pour savoir si ça marche.",
        ],
        "rendu": "L'entonnoir chiffré, le maillon faible en gras, 3 actions.",
    },
    "decision": {
        "titre": "Aide à la décision",
        "quand": "hésiter entre plusieurs choix (embaucher, acheter, accepter un chantier, investir)",
        "etapes": [
            "Les options (2 à 4), dont « ne rien faire ».",
            "Les critères qui comptent pour le patron (argent, risque, délai, image, charge de travail), avec leur poids.",
            "Chaque option notée sur chaque critère ; chiffres via business_calc quand il y en a.",
            "Risques : le pire cas de chaque option, et si on peut revenir en arrière.",
            "Recommandation et la condition qui ferait changer d'avis.",
        ],
        "rendu": "Petit tableau options × critères, puis la recommandation en une phrase.",
    },
    "concurrence": {
        "titre": "Analyse de la concurrence",
        "quand": "concurrents, se démarquer, comparer UniC aux autres",
        "etapes": [
            "Concurrents réels : seulement ceux que le patron cite ou que la recherche trouve (source).",
            "Pour chacun : offre, prix s'il est public, points forts, points faibles, présence en ligne (avis Google).",
            "Forces / faiblesses d'UniC, opportunités / menaces du marché (SWOT).",
            "2 ou 3 façons concrètes de se démarquer.",
        ],
        "rendu": "Tableau concurrents, SWOT en 4 lignes, puis les actions.",
    },
    "projet": {
        "titre": "Cadrer un projet ou un gros chantier",
        "quand": "organiser un chantier, un projet, un lancement ; planning, étapes, responsables",
        "etapes": [
            "Objectif et résultat attendu, en une phrase ; ce qui est hors du projet.",
            "Étapes et jalons datés (dates du patron ou de l'agenda).",
            "Qui fait quoi (équipe), matériel et commandes à prévoir.",
            "Risques (retard fournisseur, météo, paiement) et la parade de chacun.",
            "Suivi : quoi vérifier chaque semaine.",
        ],
        "rendu": "Liste d'étapes datées, responsables, risques ; proposer de les mettre à l'agenda (sur demande seulement).",
    },
    "finances": {
        "titre": "Lire la santé financière",
        "quand": "est-ce que l'entreprise va bien, trésorerie, rentabilité, impayés",
        "etapes": [
            "Chiffres réels : business_report (CA, marge), cash_forecast (trésorerie 90 jours), list_unpaid (impayés).",
            "Trois signaux : marge suffisante ? trésorerie qui tient 90 jours ? clients qui paient à temps ?",
            "Le point le plus urgent et son montant.",
            "2 ou 3 actions (relances, acomptes plus élevés, échéancier, coûts à réduire).",
        ],
        "rendu": "3 signaux (vert / orange / rouge) avec leur chiffre, puis l'action prioritaire.",
    },
    "appel_offres": {
        "titre": "Répondre à un appel d'offres",
        "quand": "appel d'offres, DAO, consultation, dossier de candidature",
        "etapes": [
            "Lire le dossier : pièces exigées, critères de notation, date limite, visite obligatoire, cautions.",
            "Aller / ne pas aller : capacité, délai, trésorerie, chance de gagner.",
            "Pièces administratives et références à fournir (liste à cocher).",
            "Mémoire technique : méthode de pose, planning, équipe, moyens, sécurité.",
            "Prix : métré (read_plan, calculate_from_plan) et prix du patron ; jamais de prix inventé.",
        ],
        "rendu": "Liste à cocher des pièces, décision aller/ne pas aller, plan du mémoire technique.",
    },
}


def liste() -> str:
    """Ligne courte pour la description de l'outil."""
    return " ; ".join(f"{k} ({m['quand']})" for k, m in METHODES.items())


def get(nom: str) -> dict:
    key = (nom or "").strip().lower().replace(" ", "_").replace("-", "_")
    m = METHODES.get(key)
    if m is None:
        return {"error": f"Méthode inconnue : « {nom} ». Disponibles : {', '.join(METHODES)}."}
    return {"methode": key, "titre": m["titre"], "etapes": m["etapes"], "rendu": m["rendu"], "regles": REGLES,
            "note": "Suis ces étapes dans l'ordre, avec les vrais chiffres ; ce qui manque, demande-le au patron."}
