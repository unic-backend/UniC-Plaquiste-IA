"""Formation UniC : un cours déjà écrit, à étudier dans l'appli, SANS l'IA (aucun crédit).

Contenu : la « Banque de règles » du tuteur (docs/skills/unic-tuteur/SKILL.md), rien d'autre.
Exercices : générés depuis un numéro (même numéro = même exercice), corrigés par le moteur de calcul (pieces.calculate).
Suivi : un élève par prénom, gardé dans AppSetting (clé « formation »). Aucun prix n'est montré.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

KEY = "formation"

MODULES = [
    {"id": "base", "titre": "1. Le matériel UniC", "points": [
        "Plaque par défaut : 2 m × 1,20 m. 2,50 m seulement si le patron le dit.",
        "Fourrure, montant, rail, cornière : barres de 2,80 m.",
        "Une barre n'est pas un paquet : on compte les barres une par une.",
        "Vis à plaque en paquet de 1 000 ; bande en rouleau de 150 m ; enduit en sac de 20 kg.",
    ], "pieges": ["Confondre barre et paquet : on commande des barres."]},
    {"id": "plafond", "titre": "2. Faux plafond : fourrures et tiges", "points": [
        "Une fourrure tous les 0,50 m ; la plaque est posée en travers des fourrures.",
        "Nombre de lignes : largeur ÷ 0,50, plus 1.",
        "Sur chaque ligne : la 1re tige à 0,30 m du mur, puis une tous les 0,90 m.",
        "Un point d'accroche = 1 tige + 1 pivot + 1 cheville à laiton. Sur IPN : une éclipse à la place de la cheville.",
        "Suspente de plus de 1 m : tiges de 1 m raccordées (2 tiges par point).",
        "Cornière de rive tout le tour ; une cheville à frapper tous les 30 cm.",
    ], "pieges": ["Sens des fourrures : essayer les deux sens et garder celui qui donne le moins de tiges."],
        "exemple": {"name": "Salon", "kind": "ceiling", "length_m": 5, "width_m": 4, "support": "dalle"}},
    {"id": "marge", "titre": "3. Plaques et marge", "points": [
        "Compter les plaques entières de mur à mur, puis les morceaux ; jamais « surface ÷ surface d'une plaque ».",
        "Marge du faux plafond : + 3 pièces sous 50 m² ; + 5 de 50 à 100 m² ; + 10 au-delà de 100 m².",
        "La marge se compte en pièces, jamais en paquets.",
        "Jamais de marge sur une cloison.",
    ], "pieges": ["Mettre une marge sur la cloison : c'est faux."]},
    {"id": "cloison", "titre": "4. Cloison : montants et rails", "points": [
        "Un montant tous les 0,60 m (0,50 m si la plaque est couchée).",
        "2 montants côte à côte à chaque jonction de plaques.",
        "3 montants de renfort par porte.",
        "Rails en haut et en bas : longueur × 2 ÷ 2,80, arrondi au-dessus.",
        "4 vis de 9 mm par montant.",
        "Cloison plus haute que 2,80 m : rallonge + raccord de rail de 40 cm.",
    ], "pieges": ["Plaque debout ou couchée : l'écart des montants change (0,60 ou 0,50)."],
        "exemple": {"name": "Cloison", "kind": "partition", "length_m": 6, "height_m": 2.5, "sides": 2, "doors": 1}},
    {"id": "finition", "titre": "5. Vis, bande, enduit", "points": [
        "Vis à plaque : 15 par m².",
        "Bande : 1,40 ml par m².",
        "Enduit : 0,35 kg par m² et par couche, 2 couches.",
        "Arrondir une seule fois sur tout le chantier, pas pièce par pièce.",
    ], "pieges": ["Arrondir pièce par pièce : on commande trop."]},
    {"id": "autres", "titre": "6. Lambris et électricité", "points": [
        "Lambris PVC : lames de 3 m, toujours dans le sens de la largeur.",
        "Électricité : conseil seulement (NF C 15-100), jamais chiffrée.",
        "Jamais le rouge (phase) sur le bleu (neutre).",
    ], "pieges": []},
]

# Questions de décision : réponse vérifiée côté serveur (l'élève ne voit pas la bonne réponse avant de choisir).
QUIZ = [
    {"id": "q1", "q": "Une plaque par défaut chez UniC mesure :", "choix": ["2 m × 1,20 m", "2,50 m × 1,20 m", "3 m × 1,20 m"], "ok": 0,
     "pourquoi": "2 m × 1,20 m ; 2,50 m seulement si le patron le dit."},
    {"id": "q2", "q": "Longueur d'une barre de fourrure :", "choix": ["2,50 m", "2,80 m", "3 m"], "ok": 1, "pourquoi": "Toutes les barres font 2,80 m."},
    {"id": "q3", "q": "Écart entre deux fourrures au plafond :", "choix": ["0,40 m", "0,50 m", "0,60 m"], "ok": 1, "pourquoi": "Une fourrure tous les 0,50 m."},
    {"id": "q4", "q": "La 1re tige se place à quelle distance du mur ?", "choix": ["0,30 m", "0,50 m", "0,90 m"], "ok": 0,
     "pourquoi": "0,30 m du mur, puis une tous les 0,90 m."},
    {"id": "q5", "q": "Suspente de 1,5 m : que fais-tu ?", "choix": ["Une tige de 1 m", "Deux tiges de 1 m raccordées", "Pas de tige"], "ok": 1,
     "pourquoi": "Plus de 1 m : tiges de 1 m raccordées."},
    {"id": "q6", "q": "Plafond de 60 m² : quelle marge ?", "choix": ["+ 3 pièces", "+ 5 pièces", "+ 10 pièces"], "ok": 1,
     "pourquoi": "De 50 à 100 m² : + 5 pièces."},
    {"id": "q7", "q": "Cloison de 20 m² : quelle marge ?", "choix": ["+ 3 pièces", "+ 5 pièces", "Aucune"], "ok": 2, "pourquoi": "Jamais de marge sur une cloison."},
    {"id": "q8", "q": "Écart des montants, plaque couchée :", "choix": ["0,50 m", "0,60 m", "0,90 m"], "ok": 0, "pourquoi": "0,60 m debout ; 0,50 m couchée."},
    {"id": "q9", "q": "Combien de montants de renfort par porte ?", "choix": ["1", "2", "3"], "ok": 2, "pourquoi": "3 montants de renfort par porte."},
    {"id": "q10", "q": "Sur IPN, à la place de la cheville à laiton :", "choix": ["Une éclipse", "Un pivot", "Une vis de 9 mm"], "ok": 0,
     "pourquoi": "Sur IPN : une éclipse par point d'accroche."},
    {"id": "q11", "q": "Vis à plaque par m² :", "choix": ["10", "15", "20"], "ok": 1, "pourquoi": "15 vis par m², paquet de 1 000."},
    {"id": "q12", "q": "Une cheville à frapper tous les :", "choix": ["30 cm", "50 cm", "90 cm"], "ok": 0, "pourquoi": "Une tous les 30 cm de cornière ou de rail."},
    {"id": "q13", "q": "Comment compter les plaques ?", "choix": ["Surface ÷ 2,4 m²", "Plaques entières puis morceaux", "Au hasard + 10 %"], "ok": 1,
     "pourquoi": "Plaques entières de mur à mur, puis les morceaux."},
    {"id": "q14", "q": "Le patron demande le prix de l'électricité :", "choix": ["Je chiffre", "Conseil seulement", "Je copie un vieux devis"], "ok": 1,
     "pourquoi": "Électricité : conseil seulement, jamais chiffrée."},
]
_QUIZ = {q["id"]: q for q in QUIZ}

# Ce qu'on demande dans un exercice : pièce du moteur (sku) → question + règle (l'indice, montré avant la solution).
ASK = {
    "ceiling": [
        ("BA13-2000x1200", "Combien de plaques ?", "Plaques entières de mur à mur, puis les morceaux, puis la marge du plafond."),
        ("UC-TIGES-A-L-UNITE", "Combien de tiges ?", "Sur chaque ligne : 1re tige à 0,30 m du mur, puis tous les 0,90 m. Suspente > 1 m : 2 tiges par point."),
        ("UC-BARRE-DE-FOURRURE-2-90-M", "Combien de barres de fourrure ?", "Lignes = largeur ÷ 0,50 + 1. Mètres ÷ 2,80, arrondi au-dessus, puis la marge."),
        ("UC-CORNIERES", "Combien de cornières ?", "Périmètre ÷ 2,80, arrondi au-dessus, puis la marge."),
    ],
    "partition": [
        ("BA13-2000x1200", "Combien de plaques ?", "Plaques entières, puis les morceaux, moins les ouvertures. Pas de marge."),
        ("MONTANT-M48", "Combien de montants ?", "Un tous les 0,60 m ; 2 à chaque jonction de plaques ; 3 par porte."),
        ("UC-RAILS-48-MM", "Combien de barres de rail ?", "Longueur × 2 (haut et bas) ÷ 2,80, arrondi au-dessus."),
    ],
}
TYPES = {"plafond": "ceiling", "cloison": "partition"}


def _room(kind: str, seed: int) -> dict:
    r = random.Random(f"{kind}:{seed}")
    half = lambda a, b: r.randint(a * 2, b * 2) / 2   # noqa: E731 — cotes au demi-mètre
    if kind == "ceiling":
        length = half(3, 9)
        width = min(half(3, 8), length)
        ipn = r.random() < 0.3
        room = {"name": "Pièce", "kind": "ceiling", "length_m": length, "width_m": width, "support": "ipn" if ipn else "dalle"}
        if ipn:
            room["suspente_m"] = r.choice([0.5, 1.5])
        return room
    return {"name": "Cloison", "kind": "partition", "length_m": half(3, 8), "height_m": r.choice([2.5, 2.6, 2.7]),
            "sides": 2, "doors": r.choice([0, 0, 1])}


def _m(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _enonce(room: dict) -> str:
    if room["kind"] == "ceiling":
        sup = "sur IPN" if room.get("support") == "ipn" else "sur dalle"
        sus = f", suspente de {_m(room['suspente_m'])} m" if room.get("suspente_m") else ""
        return f"Faux plafond de {_m(room['length_m'])} m × {_m(room['width_m'])} m {sup}{sus}."
    porte = "une porte" if room["doors"] else "sans porte"
    return f"Cloison de {_m(room['length_m'])} m de long et {_m(room['height_m'])} m de haut, plaques des 2 côtés, {porte}."


def _engine(db: Session, room: dict) -> dict[str, dict]:
    from app import pieces
    bloc = pieces.calculate(db, [room])["blocs"][0]
    # Quantités seulement : un ouvrier ne voit aucun prix.
    return {q["sku"]: {"nom": q["name"], "quantite": q["quantity"], "unite": q["unit"], "calcul": q["formula"]} for q in bloc["quantites"]}


def course(db: Session) -> dict:
    mods = []
    for m in MODULES:
        m = dict(m)
        if "exemple" in m:
            res = _engine(db, m["exemple"])
            m["exemple"] = {"enonce": _enonce(m["exemple"]),
                            "resultat": [{"question": q, **res[sku]} for sku, q, _ in ASK[m["exemple"]["kind"]] if sku in res]}
        mods.append(m)
    quiz = [{"id": q["id"], "q": q["q"], "choix": q["choix"]} for q in QUIZ]
    return {"modules": mods, "quiz": quiz, "types": list(TYPES)}


def exercise(db: Session, typ: str, seed: int) -> dict:
    kind = TYPES.get(typ)
    if kind is None:
        raise ValueError("Type d'exercice inconnu.")
    room = _room(kind, seed)
    res = _engine(db, room)
    qs = [{"sku": sku, "question": q, "indice": hint} for sku, q, hint in ASK[kind] if sku in res]
    return {"type": typ, "seed": seed, "enonce": _enonce(room), "questions": qs}


def _load(db: Session) -> dict:
    from app.models import AppSetting
    row = db.get(AppSetting, KEY)
    try:
        data = json.loads(row.value) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save(db: Session, data: dict) -> None:
    from app.models import AppSetting
    value = json.dumps(data, ensure_ascii=False)
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()


def _learner(data: dict, name: str) -> dict:
    name = " ".join(name.split())[:40]
    if not name:
        raise ValueError("Prénom de l'élève manquant.")
    return data.setdefault("eleves", {}).setdefault(name, {"lecons": [], "quiz": {}, "exercices": []})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def grade(db: Session, typ: str, seed: int, answers: dict, learner: str, exam: bool = False) -> dict:
    kind = TYPES.get(typ)
    if kind is None:
        raise ValueError("Type d'exercice inconnu.")
    room = _room(kind, seed)
    res = _engine(db, room)
    lines, good = [], 0
    for sku, q, _hint in ASK[kind]:
        if sku not in res:
            continue
        exp = res[sku]["quantite"]
        given = answers.get(sku)
        try:
            ok = given is not None and abs(float(given) - float(exp)) < 1e-6
        except (TypeError, ValueError):
            ok = False
        good += ok
        lines.append({"sku": sku, "question": q, "reponse": given, "attendu": exp, "unite": res[sku]["unite"], "ok": ok, "calcul": res[sku]["calcul"]})
    total = len(lines)
    pct = round(100 * good / total) if total else 0
    verdict = "refaire" if pct < 60 else "plus dur" if pct < 90 else "tâche complète"
    data = _load(db)
    el = _learner(data, learner)
    el["exercices"] = (el["exercices"] + [{"at": _now().isoformat(timespec="seconds"), "type": typ, "seed": seed,
                                           "bon": good, "total": total, "examen": bool(exam)}])[-200:]
    _save(db, data)
    return {"enonce": _enonce(room), "lignes": lines, "bon": good, "total": total, "pourcent": pct, "verdict": verdict}


CONF = ("sûr", "pas sûr", "deviné")


def answer_quiz(db: Session, learner: str, qid: str, choice: int, confidence: str) -> dict:
    q = _QUIZ.get(qid)
    if q is None:
        raise ValueError("Question inconnue.")
    if confidence not in CONF:
        raise ValueError("Certitude : sûr, pas sûr ou deviné.")
    ok = choice == q["ok"]
    # Révision : faux, pas sûr ou deviné → dans 2 jours ; juste et sûr → dans 1 semaine.
    due = _now() + timedelta(days=7 if ok and confidence == "sûr" else 2)
    data = _load(db)
    _learner(data, learner)["quiz"][qid] = {"ok": ok, "certitude": confidence, "revoir": due.isoformat(timespec="seconds")}
    _save(db, data)
    return {"ok": ok, "bonne": q["choix"][q["ok"]], "pourquoi": q["pourquoi"], "revoir": due.date().isoformat()}


def mark_lesson(db: Session, learner: str, lesson: str) -> dict:
    if lesson not in {m["id"] for m in MODULES}:
        raise ValueError("Leçon inconnue.")
    data = _load(db)
    el = _learner(data, learner)
    if lesson not in el["lecons"]:
        el["lecons"].append(lesson)
    _save(db, data)
    return progress(db, learner)


def progress(db: Session, learner: str) -> dict:
    data = _load(db)
    el = _learner(data, learner)
    now = _now().isoformat(timespec="seconds")
    revoir = [qid for qid, a in el["quiz"].items() if a.get("revoir", "") <= now and qid in _QUIZ]
    ex = el["exercices"]
    exams = [e for e in ex if e.get("examen")]
    return {"eleve": " ".join(learner.split())[:40], "lecons": el["lecons"], "total_lecons": len(MODULES),
            "quiz_faits": len(el["quiz"]), "quiz_justes": sum(1 for a in el["quiz"].values() if a.get("ok")), "total_quiz": len(QUIZ),
            "a_revoir": revoir, "exercices": len(ex), "derniers": ex[-5:][::-1], "dernier_examen": exams[-1] if exams else None}


def learners(db: Session) -> list[str]:
    return sorted(_load(db).get("eleves", {}))
