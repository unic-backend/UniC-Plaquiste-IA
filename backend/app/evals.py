"""Banc d'essai de l'IA : cas de référence REPRODUCTIBLES pour mesurer l'extraction des dimensions.

Chaque cas = une demande du patron + ce que l'IA DOIT extraire (outil, dimensions, unités converties) + ce qu'elle ne doit
JAMAIS faire (inventer les faces, la taille d'une porte, une longueur à partir d'une surface, un prix). La notation est
déterministe (code, pas un modèle) : la même réponse donne toujours la même note. Les outils ne sont PAS exécutés pendant
l'essai (aucun devis, aucune écriture) : on regarde seulement ce que le modèle demande.

À relancer après chaque changement de consigne, de modèle ou d'orchestrateur (Paramètres › Atelier › Banc d'essai IA).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("unic.evals")
SETTING_KEY = "ai_eval_last"
MIN_INTERVAL_S = 600   # un essai coûte des jetons : pas plus d'une fois toutes les 10 minutes

# expect : arguments attendus (nombres comparés à 1 % près) ; absent : arguments qui ne doivent PAS être inventés ;
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
    {"id": "peinture", "message": "Peinture de 45 m² en deux couches, il me faut combien ?",
     "tool": "calculate_materials", "expect": {"kind": "paint", "area_m2": 45, "coats": 2}},
    {"id": "prix-plaque", "message": "Combien coûte une plaque BA13 chez nous ?", "tool": "get_prices", "expect": {}},
    {"id": "devis-apres-calcul", "message": "Fais le devis d'une cloison de 6 m sur 2,50 m deux faces pour Awa Ba.",
     "tool": "calculate_materials", "expect": {"kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2},
     "not_before": "create_quote"},
]


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
    from app import agent
    from app.ai import PROVIDERS
    from app.config import settings
    from app.models import AppSetting
    from app.orchestrator import SYSTEM_RULES
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
        try:
            complete([{"role": "system", "content": SYSTEM_RULES}, {"role": "user", "content": case["message"]}],
                     tools=agent.TOOLS, tool_handler=handler, max_tokens=1500, effort="medium",
                     model=settings.anthropic_fast_model)   # mêmes réglages que la conversation courante
            results.append(score_case(case, calls))
        except Exception as exc:   # un cas en panne ne fausse pas les autres
            logger.warning("cas %s en échec : %s", case["id"], exc)
            results.append({"id": case["id"], "ok": False, "problems": [f"Erreur : {type(exc).__name__}"]})
    passed = sum(1 for r in results if r["ok"])
    report = {"at": datetime.now(timezone.utc).isoformat(), "passed": passed, "total": len(results),
              "score": round(100 * passed / len(results), 1) if results else 0.0, "results": results}
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=json.dumps(report, ensure_ascii=False)))
    else:
        row.value = json.dumps(report, ensure_ascii=False)
    db.flush()
    return report


def report_last(db: Session) -> dict | None:
    from app.models import AppSetting
    row = db.get(AppSetting, SETTING_KEY)
    try:
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None


RUNNING: set[str] = set()


def start_background() -> None:
    """Lance le banc d'essai en arrière-plan (≈ 1 min) ; le rapport apparaît ensuite dans l'Atelier."""
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
            run(session)
            session.commit()
        except Exception:
            logger.exception("banc d'essai en échec")
            session.rollback()
        finally:
            session.close()
            RUNNING.discard("run")
    threading.Thread(target=job, name="unic-eval", daemon=True).start()
