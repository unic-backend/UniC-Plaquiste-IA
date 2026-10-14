"""Calculs d'affaires DÉTERMINISTES : échéancier de paiement, délai tenable, marge, « et si… », niveaux de risque.

Idées reprises d'ARENA (`core/executive/calcul_affaires.py` et `risque_affaires.py`), réécrites pour UniC et corrigées sur un point :
l'échéancier d'ARENA arrondissait chaque étape à part, donc la somme des étapes pouvait différer du total (1 FCFA de trop ou de moins sur
une facture). Ici la somme des étapes est TOUJOURS égale au total (méthode du plus fort reste).

Pourquoi sans l'IA : un modèle de langage additionne parfois mal de tête. Ces fonctions sont vérifiables et testées.
Aucune valeur n'est inventée : une entrée manquante ou incohérente rend `valide: False` avec sa raison, jamais un chiffre par défaut.
"""
from __future__ import annotations

from typing import Any

TOLERANCE_ECHEANCIER = 0.5     # points de pourcentage : 33,3 + 33,3 + 33,4 est accepté, 90 % non

FAIBLE, MODERE, ELEVE, EXTREME, INCONNU = "FAIBLE", "MODÉRÉ", "ÉLEVÉ", "EXTRÊME", "INCONNU"
_RANG = {INCONNU: 0, FAIBLE: 1, MODERE: 2, ELEVE: 3, EXTREME: 4}


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _ko(raison: str, **extra: Any) -> dict:
    return {"valide": False, "raison": raison, **extra}


def marge(revenu: Any, couts: Any) -> dict:
    """Marge brute = revenu − somme des coûts. Refuse revenu absent/négatif, aucun coût, coût négatif ou non numérique."""
    r = _num(revenu)
    if r is None or r <= 0:
        return _ko("revenu manquant ou non positif")
    if not isinstance(couts, dict) or not couts:
        return _ko("aucun coût fourni", revenu=r)
    detail: dict[str, float] = {}
    for poste, v in couts.items():
        c = _num(v)
        if c is None:
            return _ko(f"coût non numérique : {poste}", revenu=r)
        if c < 0:
            return _ko(f"coût négatif refusé : {poste}={c:g}", revenu=r)
        detail[str(poste)] = c
    total = sum(detail.values())
    m = r - total
    return {"valide": True, "revenu": r, "cout_total": total, "detail_couts": detail,
            "marge": m, "marge_pct": round(m / r * 100, 2), "a_perte": m < 0}


def echeancier(total: Any, etapes: Any) -> dict:
    """Répartit `total` selon des pourcentages (ex. acompte 50, avancement 30, solde 20).
    Les pourcentages doivent faire 100 % (±0,5) ; la somme des montants est EXACTEMENT `total` (plus fort reste, en entiers)."""
    t = _num(total)
    if t is None or t <= 0:
        return _ko("montant total manquant ou non positif")
    if not isinstance(etapes, (list, tuple)) or not etapes:
        return _ko("aucune échéance fournie", total=t)
    libelles, pcts = [], []
    for e in etapes:
        if isinstance(e, dict):
            lib, p = e.get("libelle", e.get("label", "")), _num(e.get("pourcentage", e.get("percent")))
        elif isinstance(e, (list, tuple)) and len(e) == 2:
            lib, p = e[0], _num(e[1])
        else:
            return _ko("échéance illisible : attendu {libelle, pourcentage}", total=t)
        if p is None or p <= 0:
            return _ko(f"pourcentage invalide pour « {lib} »", total=t)
        libelles.append(str(lib)[:80] or "Échéance")
        pcts.append(p)
    somme = sum(pcts)
    if abs(somme - 100.0) > TOLERANCE_ECHEANCIER:
        return _ko(f"les pourcentages font {somme:.1f} %, pas 100 %", total=t)
    entier = float(t).is_integer()
    unite = 1.0 if entier else 0.01
    cible = round(t / unite)                                   # total en unités (FCFA entiers, sinon centimes)
    brut = [cible * p / somme for p in pcts]                   # normalisé sur la somme réelle des pourcentages
    base = [int(b) for b in brut]
    reste = cible - sum(base)
    ordre = sorted(range(len(brut)), key=lambda i: brut[i] - base[i], reverse=True)
    for i in ordre[:reste]:
        base[i] += 1
    out = [{"libelle": libelles[i], "pourcentage": pcts[i], "montant": base[i] * unite if not entier else base[i]} for i in range(len(pcts))]
    return {"valide": True, "total": t, "etapes": out, "somme_exacte": round(sum(e["montant"] for e in out), 2) == round(t, 2)}


def delai(jours_disponibles: Any, jours_estimes: Any, jours_risque: Any = 0) -> dict:
    """Le délai demandé tient-il, en comptant le risque de retard connu (ex. retard fournisseur) et pas seulement l'estimation optimiste ?"""
    d, e, r = _num(jours_disponibles), _num(jours_estimes), _num(jours_risque)
    if d is None or d <= 0:
        return _ko("délai disponible manquant ou non positif")
    if e is None or e < 0:
        return _ko("durée estimée manquante ou négative", jours_disponibles=d)
    r = max(r or 0.0, 0.0)
    m = d - (e + r)
    return {"valide": True, "jours_disponibles": d, "jours_estimes": e, "jours_risque": r, "marge_jours": m, "tenable": m >= 0}


def comparer(base: Any, variantes: Any) -> dict:
    """« Et si… » : chaque variante est comparée à la base (écart de marge), jamais aux autres variantes seules."""
    if not isinstance(base, dict):
        return _ko("scénario de base manquant")
    mb = marge(base.get("revenu"), base.get("couts"))
    if not mb["valide"]:
        return _ko("scénario de base invalide : " + mb["raison"])
    if not isinstance(variantes, (list, tuple)) or not variantes:
        return _ko("aucune variante à comparer", base=mb)
    out = []
    for v in variantes[:8]:
        if not isinstance(v, dict):
            continue
        mv = marge(v.get("revenu"), v.get("couts"))
        item: dict[str, Any] = {"nom": str(v.get("nom", "variante"))[:60], "marge": mv}
        if mv["valide"]:
            item["ecart_marge"] = round(mv["marge"] - mb["marge"], 2)
            item["ecart_pct"] = round((mv["marge"] - mb["marge"]) / abs(mb["marge"]) * 100, 1) if mb["marge"] else None
        if v.get("jours_disponibles") is not None and v.get("jours_estimes") is not None:
            item["delai"] = delai(v.get("jours_disponibles"), v.get("jours_estimes"), v.get("jours_risque", 0))
        out.append(item)
    return {"valide": True, "base": mb, "variantes": out}


# ---------- niveaux de risque (seuils d'ARENA) ----------

def _niveau(valeur: float | None, seuils: tuple[float, float, float]) -> str:
    if valeur is None:
        return INCONNU
    a, b, c = seuils
    return FAIBLE if valeur < a else MODERE if valeur < b else ELEVE if valeur < c else EXTREME


def risque_dependance_fournisseur(part: Any) -> str:
    """Part (0–1) du chantier qui repose sur UN fournisseur ou sous-traitant."""
    return _niveau(_num(part), (0.3, 0.6, 0.85))


def risque_concentration_client(part: Any) -> str:
    """Part (0–1) du chiffre d'affaires qui vient d'UN client."""
    return _niveau(_num(part), (0.2, 0.4, 0.6))


def risque_delai(marge_jours: Any, duree_totale: Any) -> str:
    m, d = _num(marge_jours), _num(duree_totale)
    if m is None or not d:
        return INCONNU
    if m < 0:
        return EXTREME
    ratio = m / d
    return ELEVE if ratio < 0.05 else MODERE if ratio < 0.15 else FAIBLE


def risque_tresorerie(depense_avant_encaissement: Any, tresorerie: Any) -> str:
    """Ce qu'il faut avancer avant le premier encaissement, comparé à la trésorerie réelle."""
    dep, treso = _num(depense_avant_encaissement), _num(tresorerie)
    if dep is None or treso is None:
        return INCONNU
    if treso <= 0:
        return EXTREME if dep > 0 else FAIBLE
    ratio = dep / treso
    return FAIBLE if ratio < 0.5 else MODERE if ratio < 0.85 else ELEVE if ratio <= 1.0 else EXTREME


def risque_global(**facteurs: Any) -> dict:
    """Le pire des niveaux MESURÉS (un facteur inconnu n'aggrave ni ne masque rien) + le détail de chaque facteur."""
    niveaux = {
        "dependance_fournisseur": risque_dependance_fournisseur(facteurs.get("dependance_fournisseur")),
        "delai": risque_delai(facteurs.get("marge_jours"), facteurs.get("duree_totale_jours")),
        "tresorerie": risque_tresorerie(facteurs.get("depense_avant_encaissement"), facteurs.get("tresorerie_disponible")),
        "concentration_client": risque_concentration_client(facteurs.get("concentration_client")),
    }
    connus = [n for n in niveaux.values() if n != INCONNU]
    return {"niveau_global": max(connus, key=lambda n: _RANG[n]) if connus else INCONNU, "facteurs": niveaux}


def concentration_clients(parts: dict[str, float]) -> dict:
    """À partir de montants facturés par client : part de chacun, le plus gros, et son niveau de risque."""
    clean = {str(k): float(v) for k, v in parts.items() if _num(v) is not None and float(v) > 0}
    total = sum(clean.values())
    if total <= 0:
        return _ko("aucun montant facturé")
    classement = sorted(((k, v, v / total) for k, v in clean.items()), key=lambda x: -x[1])
    top = classement[0]
    return {"valide": True, "total": total, "clients": [{"client": k, "montant": v, "part_pct": round(p * 100, 1)} for k, v, p in classement[:8]],
            "plus_gros": {"client": top[0], "part_pct": round(top[2] * 100, 1), "niveau": risque_concentration_client(top[2])}}
