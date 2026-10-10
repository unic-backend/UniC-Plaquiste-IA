"""Tableau « Qualité » : les progrès se mesurent, ils ne se supposent pas.

Lecture seule, aucun appel à Claude. Chaque indicateur vient de données DÉJÀ enregistrées (journal d'audit, devis et leur trace de calcul,
dernier banc d'essai, sauvegardes, surveillance du serveur, coûts). Un indicateur qu'on ne peut pas mesurer ici est rendu « non mesuré »
avec la raison : jamais un chiffre inventé.

Indicateur clé : « résultats incorrects présentés comme certains ». Il ne compte que ce que le code SAIT détecter (documents dont les
chiffres ne tombent pas juste, écarts du contrôle indépendant, inventions vues au banc d'essai). Ce qu'il ne détecte pas n'y figure pas.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

DAYS = 30
OK, WARN, BAD, NONE = "ok", "warn", "bad", "none"


def _row(id_: str, title: str, value: str, state: str, detail: str = "") -> dict[str, Any]:
    return {"id": id_, "titre": title, "valeur": value, "etat": state, "detail": detail}


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _audit_count(db: Session, action: str, since: datetime) -> int:
    from app.models import AuditLog
    return db.query(func.count(AuditLog.id)).filter(AuditLog.action == action, AuditLog.created_at >= since).scalar() or 0


def _calc_check(db: Session, since: datetime) -> tuple[int, int]:
    """(devis dont le contrôle indépendant concorde, devis contrôlés) sur la période, d'après la trace figée de chaque devis."""
    from app import provenance
    from app.models import Quotation
    ok = total = 0
    for q in db.query(Quotation).filter(Quotation.created_at >= since, Quotation.calc_trace.isnot(None)).all():
        check = (provenance.load(q) or {}).get("controle_independant")
        if not check:
            continue
        total += 1
        ok += 1 if check.get("ok") else 0
    return ok, total


def _invented(report: dict | None) -> tuple[int, int]:
    """(inventions vues au banc d'essai, nombre de cas) : un problème « inventé » = l'IA a complété ce que le patron n'avait pas dit."""
    if not report:
        return 0, 0
    n = sum(1 for r in report.get("results", []) for p in r.get("problems", []) if "inventé" in p)
    return n, int(report.get("total") or 0)


def report(db: Session, days: int = DAYS) -> dict[str, Any]:
    from app import backup, evals, integrity, usage
    from app.models import RepairJob
    since = _since(days)
    rows: list[dict] = []

    # 1. Exactitude des calculs (contrôle indépendant refait en fractions exactes sur chaque devis calculé)
    ok, total = _calc_check(db, since)
    if total:
        rows.append(_row("calculs", "Exactitude des calculs", f"{ok}/{total} concordants", OK if ok == total else BAD,
                         f"Contrôle indépendant des {total} devis calculés ces {days} derniers jours."))
    else:
        rows.append(_row("calculs", "Exactitude des calculs", "non mesuré", NONE, f"Aucun devis calculé ces {days} derniers jours."))

    # 2. Données manquantes : l'IA évite-t-elle d'inventer ? (dernier banc d'essai)
    last = evals.report_last(db)
    inv, cases = _invented(last)
    if last:
        rows.append(_row("manquantes", "Données manquantes (rien d'inventé)", f"{inv} invention(s) / {cases} cas",
                         OK if inv == 0 else BAD,
                         f"Banc d'essai du {str(last.get('at', ''))[:10]} : score {last.get('score')} %."))
    else:
        rows.append(_row("manquantes", "Données manquantes (rien d'inventé)", "non mesuré", NONE, "Lance le banc d'essai IA pour mesurer."))

    # 3. Documents / PDF conformes
    docs = integrity._documents(db)
    from app.models import Invoice, Quotation
    n_docs = (db.query(func.count(Quotation.id)).scalar() or 0) + (db.query(func.count(Invoice.id)).scalar() or 0)
    rows.append(_row("documents", "Documents conformes (totaux, TVA, versements, PDF)",
                     f"{len(docs)} anomalie(s) / {n_docs} documents", OK if not docs else BAD,
                     "; ".join(f"{d['ref']} ({d['detail']})" for d in docs[:3])))

    # 4. Tests et régression : mesurés avant chaque fusion par GitHub, pas ici
    rows.append(_row("tests", "Tests et régression", "mesuré par GitHub", NONE,
                     "Chaque modification passe les tests avant fusion (onglet Actions de GitHub). Rien n'est fusionné s'ils échouent."))

    # 5. Temps de réponse et erreurs serveur (compteur en mémoire, depuis le dernier démarrage)
    reqs = list(integrity._REQUESTS)
    if len(reqs) >= 20:
        errs = sum(1 for s, _ in reqs if s >= 500)
        p95 = sorted(ms for _, ms in reqs)[max(0, int(len(reqs) * 0.95) - 1)]
        bad = errs / len(reqs) > integrity.ERROR_RATE_ALERT or p95 > integrity.SLOW_MS
        rows.append(_row("serveur", "Temps de réponse et erreurs", f"{p95 / 1000:.1f} s (95 %) · {errs} erreur(s)", BAD if bad else OK,
                         f"Sur les {len(reqs)} dernières requêtes depuis le démarrage."))
    else:
        rows.append(_row("serveur", "Temps de réponse et erreurs", "non mesuré", NONE, "Pas assez de requêtes depuis le démarrage."))

    # 6. Coût de l'IA par réponse
    u = usage.summary(db)
    spent_n = u.get("messages_mois") or 0
    month = u.get("mois_usd") or 0
    if spent_n:
        rows.append(_row("cout", "Coût IA par réponse", f"{u['moyenne_par_message_usd']:.4f} $ en moyenne", OK,
                         f"Ce mois : {month:.2f} $ pour {spent_n} réponses (estimation au tarif public)."))
    else:
        rows.append(_row("cout", "Coût IA par réponse", "non mesuré", NONE, "Aucune réponse IA ce mois-ci."))

    # 7. Échecs d'outils (pannes internes ; les refus métier sont comptés à part)
    calls = _audit_count(db, "agent_tool", since)
    errors = _audit_count(db, "agent_tool_error", since)
    declined = _audit_count(db, "agent_tool_declined", since)
    refused = _audit_count(db, "agent_tool_refused", since)
    if calls:
        rate = _pct(errors, calls) or 0.0
        rows.append(_row("outils", "Échecs des outils", f"{errors}/{calls} ({str(rate).replace('.', ',')} %)", OK if rate < 2 else WARN if rate < 5 else BAD,
                         f"{declined} demande(s) refusée(s) par un connecteur ou une règle métier ; {refused} bloquée(s) par la protection anti-injection."))
    else:
        rows.append(_row("outils", "Échecs des outils", "non mesuré", NONE, "Aucun outil appelé sur la période (le journal des pannes démarre avec cette version)."))

    # 8. Restaurations
    st = backup.status()
    if st.get("verify_error"):
        rows.append(_row("restauration", "Sauvegardes restaurables", "échec", BAD, str(st["verify_error"])[:160]))
    elif st.get("last_verified"):
        rows.append(_row("restauration", "Sauvegardes restaurables", "vérifiée", OK, f"Dernier test de restauration : {str(st['last_verified'])[:10]}."))
    else:
        rows.append(_row("restauration", "Sauvegardes restaurables", "non mesuré", NONE, "Aucune sauvegarde vérifiée pour l'instant."))

    # 9. Corrections proposées par UniC : combien acceptées par le patron
    jobs = db.query(RepairJob).filter(RepairJob.created_at >= since).all()
    decided = [j for j in jobs if j.status in ("merged", "closed", "failed")]
    merged = sum(1 for j in decided if j.status == "merged")
    if decided:
        rows.append(_row("corrections", "Corrections validées", f"{merged}/{len(decided)}", OK if merged == len(decided) else WARN,
                         f"Corrections proposées par UniC et acceptées par le patron ({len(jobs) - len(decided)} en cours)."))
    else:
        rows.append(_row("corrections", "Corrections validées", "non mesuré", NONE, "Aucune correction décidée sur la période."))

    # 10. Alertes inutiles : impossible à mesurer sans retour du patron
    rows.append(_row("faux_positifs", "Alertes inutiles", "non mesuré", NONE,
                     "Il faut un bouton « fausse alerte » pour compter. Pas encore en place : rien n'est estimé."))

    # Indicateur clé
    wrong = len(docs) + (total - ok) + inv
    key = _row("faux_certains", "Résultats incorrects présentés comme certains", f"{wrong} détecté(s)", OK if wrong == 0 else BAD,
               f"{len(docs)} document(s) incohérent(s) + {total - ok} écart(s) du contrôle de calcul + {inv} invention(s) au banc d'essai. "
               "Ne compte que ce que le code sait détecter.")
    measured = [r for r in rows if r["etat"] != NONE]
    return {"jours": days, "cle": key, "indicateurs": rows, "mesures": len(measured), "total": len(rows),
            "mal": sum(1 for r in rows if r["etat"] == BAD) + (1 if key["etat"] == BAD else 0),
            "note": "Lecture seule. Chaque chiffre vient de données enregistrées ; « non mesuré » dit pourquoi, rien n'est inventé."}
