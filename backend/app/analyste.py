"""Analyste d'entreprise : les vrais chiffres d'UniC sur une période, comparés à la période d'avant, SANS IA.

Encaissé (versements du suivi + paiements posés directement sur une facture, sans double compte), signé (devis acceptés par le
client), facturé (factures émises, hors avoirs et factures annulées), dépenses (par catégorie, saisies annulées exclues), résultat
d'argent (encaissé − dépenses), taux d'acceptation, évolution mois par mois, meilleurs clients et dépendance, marge par chantier,
argent dû depuis longtemps. Puis des points d'attention tirés des chiffres par des règles fixes.

L'IA ne calcule pas ces totaux : elle appelle business_report et commente ce qui en sort. Rien n'est inventé : une période
vide rend des zéros, et le dire vaut mieux qu'un chiffre « estimé ».
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload

PERIODS = {
    "ce_mois": "ce mois-ci", "mois_dernier": "le mois dernier", "30_jours": "les 30 derniers jours",
    "3_mois": "les 3 derniers mois", "12_mois": "les 12 derniers mois", "cette_annee": "cette année",
    "annee_derniere": "l'année dernière", "tout": "depuis le début",
}
MOIS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
CATEGORIES = ("matériaux", "main-d'œuvre", "transport", "location", "autre")

# seuils des points d'attention (règles fixes, testées)
DROP_PCT = -20.0          # encaissé ou signé en baisse de plus de 20 %
RISE_PCT = 20.0           # dépenses en hausse de plus de 20 %
OLD_DAYS = 60             # argent dû depuis plus de 60 jours
LOW_ACCEPT_PCT = 30.0     # moins de 3 devis sur 10 acceptés…
MIN_DECIDED = 5           # …sur au moins 5 devis tranchés (2 refus sur 3 ne disent encore rien)
TOP_CLIENTS, TOP_SITES = 5, 8


class AnalyseError(ValueError):
    pass


@dataclass
class Event:
    kind: str        # encaisse | signe | facture | depense | devis | refus
    at: datetime
    amount: float
    who: str = ""    # client (ou catégorie pour une dépense)
    ref: str = ""    # id du devis concerné


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)   # Dakar = UTC toute l'année


def _month_start(d: datetime, shift: int = 0) -> datetime:
    y, m = divmod(d.year * 12 + (d.month - 1) + shift, 12)
    return datetime(y, m + 1, 1, tzinfo=timezone.utc)


def _year_start(d: datetime, shift: int = 0) -> datetime:
    return datetime(d.year + shift, 1, 1, tzinfo=timezone.utc)


def _clamp_same_span(start: datetime, end: datetime, prev_start: datetime, prev_limit: datetime) -> tuple[datetime, datetime]:
    """Période d'avant de la même durée que la période en cours, sans déborder (1er au 26 → 1er au 26 du mois d'avant)."""
    return prev_start, min(prev_start + (end - start), prev_limit)


def resolve(periode: str = "ce_mois", date_from: str = "", date_to: str = "", now: datetime | None = None) -> dict:
    """Période demandée et période de comparaison : {"du", "au", "label", "avant_du", "avant_au", "avant_label"} (fin exclue)."""
    now = now or _now()
    if date_from or date_to:
        try:
            start = datetime.strptime(date_from.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_from else datetime(2000, 1, 1, tzinfo=timezone.utc)
            end = (datetime.strptime(date_to.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)) if date_to else now
        except ValueError:
            raise AnalyseError("Dates illisibles : écris-les AAAA-MM-JJ.")
        if end <= start:
            raise AnalyseError("La date de fin doit venir après la date de début.")
        label = f"du {start:%d/%m/%Y} au {(end - timedelta(seconds=1)):%d/%m/%Y}"
        p0, p1 = start - (end - start), start
        return {"du": start, "au": end, "label": label, "avant_du": p0, "avant_au": p1, "avant_label": "à la période d'avant, de même durée"}
    key = periode if periode in PERIODS else "ce_mois"
    if key == "ce_mois":
        start, end = _month_start(now), now
        p0, p1 = _clamp_same_span(start, end, _month_start(now, -1), start)
        before = "au même nombre de jours du mois d'avant"
    elif key == "mois_dernier":
        start, end = _month_start(now, -1), _month_start(now)
        p0, p1 = _month_start(now, -2), start
        before = "au mois d'avant"
    elif key == "cette_annee":
        start, end = _year_start(now), now
        p0, p1 = _clamp_same_span(start, end, _year_start(now, -1), start)
        before = "à la même période de l'année dernière"
    elif key == "annee_derniere":
        start, end = _year_start(now, -1), _year_start(now)
        p0, p1 = _year_start(now, -2), start
        before = "à l'année d'avant"
    elif key == "3_mois":
        start, end = _month_start(now, -2), now
        p0, p1 = start - (end - start), start
        before = "aux 3 mois d'avant"
    elif key == "12_mois":
        start, end = _month_start(now, -11), now
        p0, p1 = start - (end - start), start
        before = "aux 12 mois d'avant"
    elif key == "30_jours":
        start, end = now - timedelta(days=30), now
        p0, p1 = start - timedelta(days=30), start
        before = "aux 30 jours d'avant"
    else:   # tout
        start, end = datetime(2000, 1, 1, tzinfo=timezone.utc), now
        p0 = p1 = start
        before = ""
    return {"du": start, "au": end, "label": PERIODS[key], "avant_du": p0, "avant_au": p1, "avant_label": before}


def events(db: Session) -> list[Event]:
    """Tous les mouvements d'argent et de devis, lus une fois (une petite entreprise : quelques milliers de lignes au plus)."""
    from app.models import Expense, Invoice, Payment, Quotation, Receipt
    from app.services import client_name_of
    out: list[Event] = []
    quotes = {q.id: q for q in db.query(Quotation).options(selectinload(Quotation.customer)).all()}
    names = {qid: (client_name_of(db, q) or "Client sans nom") for qid, q in quotes.items()}
    live = {qid for qid, q in quotes.items() if q.status != "cancelled" and (q.total or 0) > 0}   # comme le suivi (tracking.valid_quotes)
    mirrored: set[str] = set()
    for r in db.query(Receipt).all():
        if r.payment_id:
            mirrored.add(r.payment_id)
        if r.quotation_id in live and (r.amount or 0) and (d := _aware(r.received_at)):
            out.append(Event("encaisse", d, float(r.amount), names.get(r.quotation_id, ""), r.quotation_id))
    invoices = {i.id: i for i in db.query(Invoice).options(selectinload(Invoice.customer)).all()}
    for p in db.query(Payment).all():   # paiement posé directement sur une facture (pas le miroir d'un versement du suivi)
        inv = invoices.get(p.invoice_id)
        if p.id in mirrored or inv is None or inv.status == "cancelled" or not (p.amount or 0) or not (d := _aware(p.paid_at)):
            continue
        out.append(Event("encaisse", d, float(p.amount), client_name_of(db, inv) or "Client sans nom", inv.quotation_id or ""))
    for inv in invoices.values():
        if inv.kind == "credit" or inv.status in ("draft", "cancelled") or not (inv.total or 0):
            continue
        if d := _aware(inv.approved_at or inv.created_at):
            out.append(Event("facture", d, float(inv.total), client_name_of(db, inv) or "Client sans nom", inv.quotation_id or ""))
    for qid in live:
        q = quotes[qid]
        if q.status == "draft":
            continue
        if d := _aware(q.approved_at or q.created_at):
            out.append(Event("devis", d, float(q.total), names[qid], qid))
        decided = _aware(q.decided_at or q.approved_at or q.created_at)
        if q.client_decision == "accepted" and decided:
            out.append(Event("signe", decided, float(q.total), names[qid], qid))
        elif q.client_decision == "declined" and decided:
            out.append(Event("refus", decided, float(q.total), names[qid], qid))
    for e in db.query(Expense).filter(Expense.status != "cancelled").all():
        if (e.amount or 0) and (d := _aware(e.spent_at or e.created_at)):
            out.append(Event("depense", d, float(e.amount), (e.category or "autre"), e.quotation_id or ""))
    return out


def _in(evs: list[Event], kind: str, a: datetime, b: datetime) -> list[Event]:
    return [e for e in evs if e.kind == kind and a <= e.at < b]


def _sum(evs: list[Event]) -> float:
    return round(sum(e.amount for e in evs), 2)


def _evolution(now_v: float | None, before: float | None) -> float | None:
    if now_v is None or before is None or before == 0:
        return None
    return round(100 * (now_v - before) / abs(before), 1)


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _figures(evs: list[Event], a: datetime, b: datetime) -> dict:
    enc, dep = _sum(_in(evs, "encaisse", a, b)), _sum(_in(evs, "depense", a, b))
    acc, ref = len(_in(evs, "signe", a, b)), len(_in(evs, "refus", a, b))
    return {"encaisse": enc, "signe": _sum(_in(evs, "signe", a, b)), "facture": _sum(_in(evs, "facture", a, b)), "depenses": dep,
            "resultat": round(enc - dep, 2), "nb_devis": len(_in(evs, "devis", a, b)), "nb_signes": acc, "nb_refus": ref,
            "taux_acceptation": _pct(acc, acc + ref)}


def _months(evs: list[Event], a: datetime, b: datetime) -> list[dict]:
    """Mois par mois : ceux de la période, ou les 6 derniers si elle est courte (une tendance se voit sur plusieurs mois)."""
    last = b - timedelta(seconds=1)
    first = a if (last.year * 12 + last.month) - (a.year * 12 + a.month) >= 2 else _month_start(last, -5)
    first = max(_month_start(first), _month_start(last, -23))   # 24 mois au plus sur un graphique
    out, m = [], _month_start(first)
    while m <= last:
        n = _month_start(m, 1)
        out.append({"mois": f"{m:%Y-%m}", "label": f"{MOIS[m.month - 1]} {m.year}",
                    "encaisse": _sum(_in(evs, "encaisse", m, n)), "signe": _sum(_in(evs, "signe", m, n)),
                    "depenses": _sum(_in(evs, "depense", m, n))})
        m = n
    return out


def _clients(evs: list[Event], a: datetime, b: datetime) -> dict:
    from app import business_calc
    by: dict[str, float] = defaultdict(float)
    for e in _in(evs, "encaisse", a, b):
        by[e.who] += e.amount
    total = sum(by.values())
    rows = [{"client": k, "encaisse": round(v), "part_pct": _pct(v, total)} for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    conc = business_calc.concentration_clients(dict(by)) if total > 0 else None
    return {"top": rows[:TOP_CLIENTS], "nb": len(rows),
            "dependance": ({"client": conc["plus_gros"]["client"], "part_pct": conc["plus_gros"]["part_pct"],
                            "niveau": conc["plus_gros"]["niveau"]} if conc and conc.get("valide") else None)}


def _categories(evs: list[Event], a: datetime, b: datetime) -> list[dict]:
    by: dict[str, float] = defaultdict(float)
    for e in _in(evs, "depense", a, b):
        by[e.who] += e.amount
    total = sum(by.values())
    return [{"categorie": k, "montant": round(v), "part_pct": _pct(v, total)} for k, v in sorted(by.items(), key=lambda kv: -kv[1])]


def _sites(db: Session, ov: dict, evs: list[Event], a: datetime, b: datetime) -> list[dict]:
    """Marge des chantiers (devis acceptés) signés dans la période ou qui y ont eu des dépenses : les moins rentables d'abord."""
    from app import margin
    concerned = {e.ref for e in _in(evs, "signe", a, b)} | {e.ref for e in _in(evs, "depense", a, b) if e.ref}
    floor = margin.get_min_margin(db)
    rows = []
    for c in ov["chantiers"]:
        if c["id"] not in concerned:
            continue
        low = c["marge_pct"] is not None and (c["marge_prevue"] < 0 or (floor is not None and c["depenses"] > 0 and c["marge_pct"] < floor))
        rows.append({"numero": c["numero"], "client": c["client"], "montant": round(c["montant"]), "depenses": round(c["depenses"]),
                     "marge": round(c["marge_prevue"]), "marge_pct": c["marge_pct"], "encaisse": round(c["recu"]),
                     "sans_depense": c["depenses"] <= 0, "alerte": bool(low)})
    rows.sort(key=lambda r: (r["sans_depense"], r["marge_pct"] if r["marge_pct"] is not None else 999))
    return rows[:TOP_SITES]


def _due(ov: dict) -> dict:
    """Argent dû aujourd'hui (instantané, pas la période) : reste à encaisser et ce qui traîne depuis plus de 60 jours."""
    old = sum(t["reste"] for t in ov["anciennete"]["tranches"][2:])   # tranches 61 – 90 et + de 90 jours
    return {"reste": round(ov["reste"]), "plus_de_60_jours": round(old), "plus_ancien": ov["anciennete"]["plus_ancien"],
            "devis_sans_reponse": len(ov["sans_reponse"]), "devise": ov["devise"]}


def _fmt(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


def attention(fig: dict, before: dict | None, clients: dict, sites: list[dict], due: dict, devise: str) -> list[str]:
    """Points d'attention tirés des chiffres par des règles fixes (jamais par l'IA)."""
    out: list[str] = []
    if before:
        for key, label in (("encaisse", "Encaissements"), ("signe", "Devis signés")):
            ev = _evolution(fig[key], before[key])
            if ev is not None and ev <= DROP_PCT:
                out.append(f"{label} en baisse de {abs(ev):.0f} % ({_fmt(fig[key])} contre {_fmt(before[key])} {devise}).")
        ev = _evolution(fig["depenses"], before["depenses"])
        if ev is not None and ev >= RISE_PCT:
            out.append(f"Dépenses en hausse de {ev:.0f} % ({_fmt(fig['depenses'])} contre {_fmt(before['depenses'])} {devise}).")
    if fig["resultat"] < 0:
        out.append(f"Plus de dépenses que d'encaissements sur la période : {_fmt(fig['resultat'])} {devise}.")
    dep = clients.get("dependance")
    if dep and dep["niveau"] in ("ÉLEVÉ", "EXTRÊME") and clients.get("nb", 0) > 1:
        out.append(f"Dépendance à un client : {dep['client']} pèse {dep['part_pct']:.0f} % des encaissements (risque {dep['niveau'].lower()}).")
    for s in [s for s in sites if s["alerte"]][:3]:
        out.append(f"Chantier {s['numero']} ({s['client']}) : marge de {s['marge_pct']:.0f} % seulement ({_fmt(s['marge'])} {devise}).")
    if due["plus_de_60_jours"] > 0:
        old = due.get("plus_ancien") or {}
        out.append(f"{_fmt(due['plus_de_60_jours'])} {devise} dus depuis plus de {OLD_DAYS} jours"
                   + (f" (le plus ancien : {old.get('client')}, {old.get('jours')} jours)." if old else "."))
    if fig["taux_acceptation"] is not None and fig["taux_acceptation"] < LOW_ACCEPT_PCT and fig["nb_signes"] + fig["nb_refus"] >= MIN_DECIDED:
        out.append(f"Seulement {fig['taux_acceptation']:.0f} % des devis tranchés ont été acceptés.")
    if due["devis_sans_reponse"]:
        out.append(f"{due['devis_sans_reponse']} devis sans réponse du client : une relance est prête dans Encaissements.")
    return out


def report(db: Session, periode: str = "ce_mois", date_from: str = "", date_to: str = "", now: datetime | None = None) -> dict:
    """Le bilan chiffré de la période, comparé à la période d'avant, avec ses points d'attention."""
    from app import tracking
    p = resolve(periode, date_from, date_to, now)
    ov = tracking.overview(db)   # suivi des encaissements : chantiers, argent dû (lu une fois)
    evs = events(db)
    fig = _figures(evs, p["du"], p["au"])
    before = _figures(evs, p["avant_du"], p["avant_au"]) if p["avant_au"] > p["avant_du"] else None
    devise = ov.get("devise") or "FCFA"
    clients = _clients(evs, p["du"], p["au"])
    sites = _sites(db, ov, evs, p["du"], p["au"])
    due = _due(ov)
    chiffres = {k: {"valeur": v, "avant": before[k] if before else None,
                    "evolution_pct": _evolution(v, before[k]) if before else None} for k, v in fig.items()}
    return {
        "periode": {"label": p["label"], "du": p["du"].date().isoformat(), "au": (p["au"] - timedelta(seconds=1)).date().isoformat()},
        "comparaison": ({"label": p["avant_label"], "du": p["avant_du"].date().isoformat(),
                         "au": (p["avant_au"] - timedelta(seconds=1)).date().isoformat()} if before else None),
        "devise": devise, "chiffres": chiffres, "par_mois": _months(evs, p["du"], p["au"]), "clients": clients,
        "depenses_par_categorie": _categories(evs, p["du"], p["au"]), "chantiers": sites, "a_encaisser": due,
        "points_attention": attention(fig, before, clients, sites, due, devise),
        "vide": not any(e for e in evs if p["du"] <= e.at < p["au"]),
        "note": "Chiffres calculés sur la base UniC (suivi, factures, dépenses), sans IA. Encaissé = argent reçu ; signé = devis acceptés.",
    }


LABELS = {"encaisse": "Encaissé", "signe": "Devis signés", "facture": "Facturé", "depenses": "Dépenses", "resultat": "Résultat (encaissé − dépenses)"}


def _line(key: str, c: dict, devise: str) -> str:
    ev = c.get("evolution_pct")
    trend = "" if c.get("avant") is None else (f" (avant : {_fmt(c['avant'])} {devise}" + (f", {ev:+.0f} %)" if ev is not None else ")"))
    return f"- **{LABELS[key]}** : {_fmt(c['valeur'])} {devise}{trend}"


def _fr(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 else iso


def to_pdf(db: Session, rep: dict, user_id: str | None = None):
    """Le bilan en PDF (chiffres, graphique mois par mois, points d'attention, clients, dépenses, chantiers). Rend l'Artifact."""
    from app import makefiles
    d, ch = rep["devise"], rep["chiffres"]
    per = rep["periode"]
    lines = [f"Période : {per['label']} (du {_fr(per['du'])} au {_fr(per['au'])})."]
    if rep.get("comparaison"):
        cmp = rep["comparaison"]
        lines.append(f"Comparé {cmp['label']} (du {_fr(cmp['du'])} au {_fr(cmp['au'])}).")
    lines += ["", "# Chiffres clés"]
    lines += [_line(k, ch[k], d) for k in LABELS]
    taux = ch["taux_acceptation"]["valeur"]
    lines.append(f"- **Devis** : {ch['nb_devis']['valeur']} émis, {ch['nb_signes']['valeur']} signés"
                 + (f", {taux:.0f} % des devis tranchés acceptés" if taux is not None else ""))
    lines += ["", "[[graphique 1]]", "", "# Points d'attention"]
    lines += [f"- {p}" for p in rep["points_attention"]] or ["- Rien d'anormal dans les chiffres de la période."]
    if rep["clients"]["top"]:
        lines += ["", "# Meilleurs clients (encaissé)"]
        lines += [f"- {c['client']} : {_fmt(c['encaisse'])} {d} ({c['part_pct']:.0f} %)" for c in rep["clients"]["top"]]
    if rep["depenses_par_categorie"]:
        lines += ["", "# Dépenses par catégorie"]
        lines += [f"- {c['categorie']} : {_fmt(c['montant'])} {d} ({c['part_pct']:.0f} %)" for c in rep["depenses_par_categorie"]]
    if rep["chantiers"]:
        lines += ["", "# Chantiers"]
        lines += [f"- {s['numero']} · {s['client']} : {_fmt(s['montant'])} {d}, dépenses {_fmt(s['depenses'])} {d}, "
                  + (f"marge {_fmt(s['marge'])} {d} ({s['marge_pct']:.0f} %)" if not s["sans_depense"] else "aucune dépense saisie")
                  + (" ⚠" if s["alerte"] else "") for s in rep["chantiers"]]
    due = rep["a_encaisser"]
    lines += ["", "# Argent dû aujourd'hui", f"- Reste à encaisser : {_fmt(due['reste'])} {d}",
              f"- Dont plus de {OLD_DAYS} jours : {_fmt(due['plus_de_60_jours'])} {d}", "", rep["note"]]
    months = rep["par_mois"]
    chart = {"titre": "Mois par mois", "labels": [m["label"] for m in months],
             "series": [{"nom": "Encaissé", "valeurs": [m["encaisse"] for m in months], "couleur": "#2E7D4F"},
                        {"nom": "Signé", "valeurs": [m["signe"] for m in months], "couleur": "#B86B2F"},
                        {"nom": "Dépenses", "valeurs": [m["depenses"] for m in months], "couleur": "#6B7280"}]}
    title = f"Bilan — {per['label']}"
    return makefiles.make_pdf(db, title, "\n".join(lines), user_id, charts=[chart])
