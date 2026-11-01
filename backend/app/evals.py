"""Banc d'essai de l'IA : cas de référence REPRODUCTIBLES pour mesurer l'extraction des dimensions.

Chaque cas = une demande du patron + ce que l'IA DOIT extraire (outil, dimensions, unités converties) + ce qu'elle ne doit
JAMAIS faire (inventer les faces, la taille d'une porte, une longueur à partir d'une surface, un prix). La notation est
déterministe (code, pas un modèle) : la même réponse donne toujours la même note. Les outils ne sont PAS exécutés pendant
l'essai (aucun devis, aucune écriture) : on regarde seulement ce que le modèle demande.

À relancer après chaque changement de consigne, de modèle ou d'orchestrateur (Paramètres › Atelier › Banc d'essai IA).
Examen hebdomadaire (facultatif, coupé par défaut : il coûte des jetons) : relancé tout seul tous les 7 jours ; si la note baisse,
si un cas qui passait échoue ou si l'IA invente, le patron est prévenu par le canal des alertes (incident « examen IA »).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("unic.evals")
SETTING_KEY = "ai_eval_last"
WEEKLY_KEY = "ai_eval_weekly"     # « 1 » : examen relancé tout seul chaque semaine (réglage du patron)
HISTORY_KEY = "ai_eval_history"   # notes des derniers examens, pour voir la tendance
HISTORY_MAX = 12
WEEK_S = 7 * 86400
MIN_INTERVAL_S = 600   # un essai coûte des jetons : pas plus d'une fois toutes les 10 minutes

# expect : arguments attendus (nombres comparés à 1 % près) ; absent : arguments qui ne doivent PAS être inventés ;
# contains : texte attendu dans un argument (sans tenir compte des majuscules) ;
# tool : premier outil de calcul attendu ; not_before : outil interdit avant le calcul.
CASES: list[dict[str, Any]] = [
    {"id": "cloison-320", "message": "Calcule une cloison de 320 m de long sur 2,50 m de haut, deux faces.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 320, "height_m": 2.5, "sides": 2}},
    {"id": "faces-non-dites", "message": "J'ai une cloison de 3 m sur 2,60 m à faire, tu me sors les quantités ?",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 3, "height_m": 2.6}, "absent": ["sides"]},
    {"id": "mm-vers-m", "message": "Cloison de 3500 mm par 2500 mm, double face, calcule les matériaux.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 3.5, "height_m": 2.5, "sides": 2}},
    {"id": "porte-sans-taille", "message": "Cloison 4 m sur 2m50, une seule face, avec une porte. Calcule.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 4, "height_m": 2.5, "sides": 1},
     "openings": {"door": 1}, "absent_in_openings": ["width_m", "height_m"]},
    {"id": "sans-ouverture", "message": "Cloison de 12 m sur 2,70 m, 2 faces, aucune porte ni fenêtre. Quantités ?",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 12, "height_m": 2.7, "sides": 2, "no_openings": True}},
    {"id": "plafond-cotes", "message": "Faux plafond BA13 de 5 m sur 4 m, calcule-moi le matériel.",
     "tool": "calculate_materials", "expect": {"kind": "ceiling"}, "dims": [5, 4]},
    {"id": "plafond-surface", "message": "Faux plafond de 20 m², combien de matériel ?",
     "tool": "calculate_materials", "expect": {"kind": "ceiling", "area_m2": 20}, "absent": ["length_m", "width_m"]},
    {"id": "surface-seule", "message": "Fais-moi un devis pour 200 m² de cloison.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "area_m2": 200}, "absent": ["sides", "length_m", "height_m", "openings"],
     "not_before": "create_quote"},
    {"id": "surface-sans-ouvrage", "message": "J'ai une surface de 100 m², calcule-moi le matériel.",   # ni plafond ni cloison dit
     "tool": "calculate_materials", "expect": {"kind": "a_preciser", "area_m2": 100}},
    {"id": "plafond-materiel", "message": "Faux plafond BA13 de 6 m sur 5 m, sors-moi tout le matériel.",
     "tool": "calculate_materials", "expect": {"kind": "ceiling"}, "dims": [6, 5]},
    {"id": "peinture", "message": "Peinture de 45 m² en deux couches, il me faut combien ?",
     "tool": "calculate_materials", "expect": {"kind": "paint", "area_m2": 45, "coats": 2}},
    {"id": "prix-plaque", "message": "Combien coûte une plaque BA13 chez nous ?", "tool": "get_prices", "expect": {}},
    {"id": "devis-apres-calcul", "message": "Fais le devis d'une cloison de 6 m sur 2,50 m deux faces pour Awa Ba.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2},
     "not_before": "create_quote"},
    # au-delà du chantier : UniC est universel (courrier, fichiers, agenda) et n'invente ni adresse ni action
    {"id": "mail-banque", "message": "Écris un e-mail à ma banque (conseiller@banque.sn) pour demander un rendez-vous mardi matin.",
     "tool": "save_email_draft", "expect": {"to": "conseiller@banque.sn"}},
    {"id": "mail-sans-adresse", "message": "Écris un mail à mon fournisseur de ciment pour lui demander ses nouveaux prix.",
     "tool": "save_email_draft", "expect": {}, "absent": ["to"]},
    {"id": "excel-depenses", "message": "Fais-moi un fichier Excel de mes dépenses : ciment 50 000, fer 20 000, transport 15 000.",
     "tool": "make_spreadsheet", "expect": {}},
    {"id": "pdf-attestation", "message": "Rédige en PDF une attestation de fin de travaux pour Mme Diop, chantier de Ouakam.",
     "tool": "make_pdf", "expect": {}},
    {"id": "rendez-vous", "message": "Note un rendez-vous avec Awa jeudi à 10 h pour un métré.",
     "tool": "add_appointment", "expect": {}},
    # fonctions ajoutées par la feuille de route du diagnostic (étapes 4 à 10)
    {"id": "facture-emise", "message": "Sur la facture UC-2026-1008-MR-F, passe la quantité de la ligne 1 à 12.",
     "tool": "revise_document", "expect": {"kind": "invoice", "number": "UC-2026-1008-MR-F"}, "not_before": "create_invoice"},
    {"id": "depense-chantier", "message": "J'ai payé 150 000 de plaques BA13 pour le chantier de Moussa Diop.",
     "tool": "record_expense", "expect": {"amount": 150000, "category": "matériaux"}},
    {"id": "versement", "message": "Moussa Diop m'a versé 200 000 d'avance sur son devis.",
     "tool": "record_receipt", "expect": {"amount": 200000}},
    {"id": "tache", "message": "Note de commander les rails chez Sotiba demain matin.",
     "tool": "add_appointment", "expect": {"kind": "tache"}},
    {"id": "video-chat", "message": "Fais-moi une vidéo de 30 secondes pour présenter UniC sur TikTok.",
     "tool": "plan_video", "expect": {}},
    # chiffres de l'entreprise : toujours lus par un outil, jamais calculés de tête ni inventés
    {"id": "bilan-mois", "message": "Combien j'ai encaissé ce mois-ci et qui est mon meilleur client ?",
     "tool": "business_report", "expect": {}},
    {"id": "tresorerie", "message": "Est-ce que j'aurai assez d'argent pour payer mes charges dans les deux prochains mois ?",
     "tool": "cash_forecast", "expect": {}},
    {"id": "solde-donne", "message": "Aujourd'hui j'ai 2 500 000 FCFA en caisse et en banque, note-le pour la trésorerie.",
     "tool": "set_cash_balance", "expect": {"montant": 2500000}},
    # métier du patron : moulures, pièces humides, idées dessinées, décisions à plusieurs
    {"id": "moulure", "message": "Faux plafond de 5 m sur 4 m avec la moulure tout autour, calcule le matériel.",
     "tool": "calculate_materials", "expect": {"kind": "ceiling", "with_moulure": True}, "dims": [5, 4]},
    {"id": "hydrofuge-sdb", "message": "Faux plafond de la salle de bain, 3 m sur 2,50 m, calcule le matériel.",
     "tool": "calculate_materials", "expect": {"kind": "ceiling", "hydrofuge": True}, "dims": [3, 2.5]},
    {"id": "idees-chambre", "message": "Montre-moi des idées de plafond pour une chambre de 4 m sur 3,50 m.",
     "tool": "ceiling_designs", "expect": {}, "dims": [4, 3.5], "contains": {"piece": "chambre"}, "absent": ["styles"]},
    {"id": "plan-de-pose", "message": "Fais le plan de pose du plafond de 6 m sur 3,70 m pour mes ouvriers.",
     "tool": "pose_plan", "expect": {}, "dims": [6, 3.7]},
    {"id": "table-ronde", "message": "Table ronde : pour mon camion, je prends un prêt bancaire ou je continue à louer ?",
     "tool": "round_table", "expect": {}},
]


# Réponses de Claude qui comptent comme une réponse de l'IA (notée) ; toute autre erreur = Claude injoignable (crédit, quota, clé, réseau)
ANSWERED_ERRORS = ("empty", "refusal")


def _close(a: Any, b: Any) -> bool:
    if isinstance(b, bool) or isinstance(a, bool):
        return a is b or a == b
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return abs(a - b) <= max(0.01 * abs(b), 1e-6)
    return a == b


def score_case(case: dict, calls: list[tuple[str, dict]]) -> dict:
    """Note d'un cas à partir des appels d'outils demandés par le modèle (dans l'ordre). Déterministe."""
    problems: list[str] = []
    names = [n for n, _ in calls]
    target = case["tool"]
    if target not in names:
        return {"id": case["id"], "ok": False, "problems": [f"Outil attendu « {target} » non appelé (appels : {', '.join(names) or 'aucun'})."]}
    idx = names.index(target)
    args = calls[idx][1] or {}
    if case.get("not_before") and case["not_before"] in names[:idx]:
        problems.append(f"« {case['not_before']} » appelé avant le calcul.")
    for k, v in case.get("expect", {}).items():
        if k not in args:
            problems.append(f"{k} manquant (attendu {v}).")
        elif not _close(args[k], v):
            problems.append(f"{k} = {args[k]} (attendu {v}).")
    for k in case.get("absent", []):
        if k in args and args[k] not in (None, "", [], False):
            problems.append(f"{k} inventé ({args[k]}) alors que le patron ne l'a pas donné.")
    for k, v in case.get("contains", {}).items():
        if v.lower() not in str(args.get(k) or "").lower():
            problems.append(f"{k} = {args.get(k)!r} (doit contenir « {v} »).")
    if case.get("dims"):
        got = sorted(float(args.get(k) or 0) for k in ("length_m", "width_m"))
        if not all(_close(g, e) for g, e in zip(got, sorted(case["dims"]))):
            problems.append(f"Cotes {got} (attendu {sorted(case['dims'])}).")
    if case.get("openings"):
        ops = args.get("openings") or []
        for kind, n in case["openings"].items():
            have = sum(int(o.get("count") or 1) for o in ops if isinstance(o, dict) and o.get("kind") == kind)
            if have != n:
                problems.append(f"{kind} : {have} (attendu {n}).")
        for k in case.get("absent_in_openings", []):
            if any(isinstance(o, dict) and o.get(k) for o in ops):
                problems.append(f"Taille d'ouverture inventée ({k}).")
    return {"id": case["id"], "ok": not problems, "problems": problems, "args": args}


def run(db: Session, cases: list[dict] | None = None, complete=None) -> dict:
    """Lance le banc d'essai sur Claude (outils NON exécutés) et garde le rapport. `complete` remplaçable en test."""
    from app import agent, claims
    from app.ai import PROVIDERS
    from app.config import settings
    from app.orchestrator import SYSTEM_RULES, wants_deep
    last = report_last(db)
    if complete is None:
        if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last["at"])).total_seconds() < MIN_INTERVAL_S:
            raise ValueError("Banc d'essai lancé il y a moins de 10 minutes : attends un peu (chaque essai coûte des jetons).")
        claude = PROVIDERS["claude"]
        if not claude.health().get("available"):
            raise ValueError("Claude n'est pas configuré : le banc d'essai mesure Claude, rien n'est lancé.")
        complete = claude.complete
    results = []
    for case in cases or CASES:
        calls: list[tuple[str, dict]] = []

        def handler(name: str, args: dict, _calls=calls) -> dict:
            _calls.append((name, dict(args or {})))
            return {"evaluation": True, "note": "Banc d'essai : outil non exécuté. Réponds en une phrase."}
        # mêmes consignes, même modèle et même effort que la vraie conversation : sinon on mesure une autre IA
        deep = wants_deep(db, case["message"], asked=False, voice=False, attached=False, focus=False)
        system = SYSTEM_RULES + agent.AGENT_PROMPT + agent.availability_note(db)
        try:
            res = complete([{"role": "system", "content": system}, {"role": "user", "content": case["message"]}],
                           tools=agent.TOOLS, tool_handler=handler, max_tokens=4000, effort="high" if deep else "medium",
                           model=settings.anthropic_model if deep else settings.anthropic_fast_model)
            err = str(getattr(res, "error", "") or "")
            if not calls and err and err not in ANSWERED_ERRORS and not (getattr(res, "text", "") or ""):
                # Claude n'a pas répondu (crédit, quota, clé, réseau) : ce n'est pas l'IA qui se trompe, rien n'est noté pour ce cas
                results.append({"id": case["id"], "ok": False, "unanswered": True, "problems": [f"Claude n'a pas répondu : {err[:200]}"]})
                continue
            scored = score_case(case, calls)
            phantom = claims.unbacked(getattr(res, "text", "") or "", [n for n, _ in calls])
            if phantom:   # « j'ai créé… » sans l'outil : une action inventée compte comme une invention
                scored["problems"].append("Action inventée : la réponse affirme avoir fait " + ", ".join(phantom) + " sans l'outil.")
                scored["ok"] = False
            results.append(scored)
        except Exception as exc:   # un cas en panne ne fausse pas les autres
            logger.warning("cas %s en échec : %s", case["id"], exc)
            results.append({"id": case["id"], "ok": False, "problems": [f"Erreur : {type(exc).__name__}"]})
    answered = [r for r in results if not r.get("unanswered")]
    passed = sum(1 for r in answered if r["ok"])
    report = {"at": datetime.now(timezone.utc).isoformat(), "passed": passed, "total": len(answered),
              "unanswered": len(results) - len(answered),
              "score": round(100 * passed / len(answered), 1) if answered else 0.0, "results": results}
    if results and not answered:   # panne de Claude, pas une mauvaise note : rien dans la tendance, rien comparé à l'examen précédent
        first = next(r["problems"][0] for r in results if r.get("unanswered"))
        report["error"] = (f"{first} — sur les {len(results)} cas : l'IA n'est pas notée. Vérifie le crédit Claude "
                           "(menu › Coût de Claude) et la clé, puis relance.")
    _put(db, SETTING_KEY, json.dumps(report, ensure_ascii=False))
    if answered:
        hist = (history(db) + [{"at": report["at"], "score": report["score"], "passed": passed, "total": len(answered)}])[-HISTORY_MAX:]
        _put(db, HISTORY_KEY, json.dumps(hist, ensure_ascii=False))
    db.flush()
    return report


def _put(db: Session, key: str, value: str) -> None:
    from app.models import AppSetting
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def history(db: Session) -> list[dict]:
    from app.models import AppSetting
    row = db.get(AppSetting, HISTORY_KEY)
    try:
        data = json.loads(row.value) if row and row.value else []
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def weekly_enabled(db: Session) -> bool:
    from app.models import AppSetting
    row = db.get(AppSetting, WEEKLY_KEY)
    return bool(row and row.value == "1")


def set_weekly(db: Session, on: bool) -> None:
    _put(db, WEEKLY_KEY, "1" if on else "0")
    db.flush()


def regressions(prev: dict | None, now: dict) -> list[str]:
    """Ce qui a empiré depuis l'examen précédent : note en baisse, cas qui passait et échoue, invention. Vide = rien à signaler."""
    out: list[str] = []
    if now.get("error"):   # Claude n'a pas répondu : ce n'est pas une régression de l'IA (la panne est signalée à part)
        return out
    if prev and now["score"] < prev.get("score", 0):
        out.append(f"note en baisse : {now['score']} % (avant {prev.get('score')} %)")
    before = {r["id"] for r in (prev or {}).get("results", []) if r.get("ok")}
    broke = [r["id"] for r in now["results"] if not r["ok"] and not r.get("unanswered") and r["id"] in before]
    if broke:
        out.append("cas qui passaient et échouent : " + ", ".join(broke))
    invented = [r["id"] for r in now["results"] if any("invent" in p.lower() for p in r.get("problems", []))]
    if invented:
        out.append("l'IA invente (dimension, adresse ou action) : " + ", ".join(invented))
    return out


def weekly_due(db: Session, now: datetime | None = None) -> bool:
    """Examen de la semaine à lancer : réglage actif, aucun en cours, le dernier date de 7 jours ou plus (ou n'existe pas)."""
    if not weekly_enabled(db) or "run" in RUNNING:
        return False
    last = report_last(db)
    if not last:
        return True
    try:
        age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(last["at"])).total_seconds()
    except (KeyError, ValueError):
        return True
    return age >= WEEK_S


def report_last(db: Session) -> dict | None:
    from app.models import AppSetting
    row = db.get(AppSetting, SETTING_KEY)
    try:
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None


RUNNING: set[str] = set()


def start_background(weekly: bool = False) -> None:
    """Lance le banc d'essai en arrière-plan (≈ 1 min) ; le rapport apparaît ensuite dans l'Atelier.
    `weekly` : examen automatique de la semaine — ce qui a empiré devient un incident « examen IA » (alerte au patron)."""
    import threading
    from app.database import SessionLocal
    if "run" in RUNNING:
        raise ValueError("Banc d'essai déjà en cours.")
    db = SessionLocal()
    try:
        last = report_last(db)
        if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last["at"])).total_seconds() < MIN_INTERVAL_S:
            raise ValueError("Banc d'essai lancé il y a moins de 10 minutes : attends un peu (chaque essai coûte des jetons).")
    finally:
        db.close()
    RUNNING.add("run")

    def job() -> None:
        session = SessionLocal()
        try:
            prev = report_last(session)
            report = run(session)
            session.commit()
            worse = regressions(prev, report) if weekly else []
            if weekly and report.get("error"):   # examen de la semaine impossible : le patron le sait (sinon l'alerte ne viendrait jamais)
                from app import selfcare
                year, week, _ = datetime.now(timezone.utc).isocalendar()
                selfcare.report(f"examen IA {year}-S{week:02d}", "Examen de l'IA impossible : " + report["error"], kind="check")
            if worse:   # un seul incident par semaine (la semaine est dans la source : l'alerte de la semaine suivante repart)
                from app import selfcare
                year, week, _ = datetime.now(timezone.utc).isocalendar()
                selfcare.report(f"examen IA {year}-S{week:02d}", f"Examen de l'IA ({report['passed']}/{report['total']}) : " + " ; ".join(worse) + ".",
                                kind="check")
        except Exception:
            logger.exception("banc d'essai en échec")
            session.rollback()
        finally:
            session.close()
            RUNNING.discard("run")
    threading.Thread(target=job, name="unic-eval", daemon=True).start()
