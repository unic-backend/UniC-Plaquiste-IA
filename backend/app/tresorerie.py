"""Trésorerie prévisionnelle : combien d'argent il y aura, semaine par semaine, sur les 90 prochains jours, SANS IA.

Point de départ : le solde que le patron donne (caisse + banque + Wave), mis à jour par ce qui est entré (versements, paiements)
et sorti (dépenses, paie des ouvriers) depuis. Puis, pour l'avenir :
- entrées : le reste à encaisser des devis acceptés, à la date choisie par le patron (rappel d'encaissement) ou, à défaut, à
  l'échéance de la facture ; sans date ou déjà en retard, l'argent est incertain ;
- sorties : charges fixes du mois (loyer, abonnements… données par le patron), reste dû aux ouvriers (tout de suite), dépenses
  déjà prévues (datées dans le futur), et, en prudent, les dépenses courantes au rythme des 90 derniers jours.

Deux scénarios, jamais un seul chiffre présenté comme sûr :
- PRUDENT : seulement l'argent attendu à une date à venir ; les retards et les sans-date ne rentrent pas ; dépenses courantes comptées.
- PROBABLE : les retards rentrent dans 15 jours, les sans-date dans 30 ; pas de dépenses courantes estimées en plus.
Alerte quand le scénario prudent passe sous le seuil du patron (0 par défaut). La dépense « main-d'œuvre » qu'une journée
d'ouvrier crée sur un chantier n'est pas une sortie d'argent : c'est la paie remise à l'ouvrier qui en est une.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

KEY = "tresorerie"
HORIZON_DAYS = 90
WEEKS = 13
LATE_IN_DAYS = 15          # scénario probable : un encaissement en retard arrive dans 15 jours…
UNDATED_IN_DAYS = 30       # … et un encaissement sans date dans 30
AVERAGE_DAYS = 90          # rythme des dépenses courantes (scénario prudent)
ALERT_DAYS = 30            # alerte du patron : trou prévu dans les 30 jours
MAX_CHARGES = 30


class TresorerieError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)   # Dakar = UTC


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(d: datetime) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _fmt(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


# ---------- réglages du patron ----------

def options(db: Session) -> dict:
    from app.models import AppSetting
    row = db.get(AppSetting, KEY)
    try:
        data = json.loads(row.value) if row and row.value else {}
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"solde": data.get("solde"), "solde_at": data.get("solde_at") or "", "seuil": float(data.get("seuil") or 0),
            "charges": [c for c in data.get("charges") or [] if isinstance(c, dict)][:MAX_CHARGES]}


def _put(db: Session, cfg: dict) -> None:
    from app.models import AppSetting
    value = json.dumps(cfg, ensure_ascii=False)
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    db.flush()


def _amount(v, what: str = "Montant", allow_negative: bool = False) -> float:
    try:
        f = float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise TresorerieError(f"{what} illisible.")
    if f != f or abs(f) > 1e12 or (f < 0 and not allow_negative):
        raise TresorerieError(f"{what} hors limites.")
    return round(f, 2)


def set_balance(db: Session, amount, now: datetime | None = None) -> dict:
    """Le patron donne son solde du moment (caisse + banque + Wave). Il peut être négatif (découvert)."""
    cfg = {**options(db), "solde": _amount(amount, "Solde", allow_negative=True), "solde_at": (now or _now()).isoformat(timespec="seconds")}
    _put(db, cfg)
    return cfg


def set_options(db: Session, *, charges: list | None = None, seuil=None) -> dict:
    """Charges fixes mensuelles [{libelle, montant, jour}] et seuil d'alerte (0 par défaut)."""
    cfg = options(db)
    if charges is not None:
        clean = []
        for c in charges[:MAX_CHARGES + 1]:
            label = " ".join(str((c or {}).get("libelle") or "").split())[:80]
            if not label:
                continue
            day = int(_amount((c or {}).get("jour") or 1, "Jour"))
            if not 1 <= day <= 31:
                raise TresorerieError(f"« {label} » : jour du mois entre 1 et 31.")
            clean.append({"libelle": label, "montant": _amount(c.get("montant"), f"Montant de « {label} »"), "jour": day})
        if len(clean) > MAX_CHARGES:
            raise TresorerieError(f"{MAX_CHARGES} charges fixes au plus.")
        cfg["charges"] = clean
    if seuil is not None:
        cfg["seuil"] = _amount(seuil, "Seuil", allow_negative=True)
    _put(db, cfg)
    return cfg


# ---------- les mouvements ----------

def _labour_expense_ids(db: Session) -> set[str]:
    from app.models import WorkEntry
    return {w.expense_id for w in db.query(WorkEntry.expense_id).filter(WorkEntry.expense_id.isnot(None)).all()}


def _cash_out(db: Session) -> list[tuple[datetime, float, str]]:
    """Sorties d'argent réelles ou prévues : dépenses (hors main-d'œuvre comptée à la journée) et paie remise aux ouvriers."""
    from app.models import Expense, WorkerPayment
    labour = _labour_expense_ids(db)
    out = [(d, float(e.amount), e.label or e.category or "dépense") for e in db.query(Expense).filter(Expense.status != "cancelled").all()
           if e.id not in labour and (e.amount or 0) and (d := _aware(e.spent_at or e.created_at))]
    out += [(d, float(p.amount), "paie ouvrier") for p in db.query(WorkerPayment).filter(WorkerPayment.status != "cancelled").all()
            if (p.amount or 0) and (d := _aware(p.paid_at))]
    return out


def current_balance(db: Session, now: datetime | None = None) -> dict | None:
    """Solde d'aujourd'hui : celui donné par le patron + entrées − sorties depuis. None tant qu'il n'a rien donné."""
    from app import analyste
    cfg = options(db)
    if cfg["solde"] is None or not cfg["solde_at"]:
        return None
    now = now or _now()
    since = _aware(datetime.fromisoformat(cfg["solde_at"]))
    ins = sum(e.amount for e in analyste.events(db) if e.kind == "encaisse" and since < e.at <= now)
    outs = sum(a for d, a, _ in _cash_out(db) if since < d <= now)
    return {"donne": cfg["solde"], "donne_le": since.date().isoformat(), "entrees_depuis": round(ins), "sorties_depuis": round(outs),
            "aujourdhui": round(cfg["solde"] + ins - outs, 2)}


def _expected_in(db: Session, now: datetime) -> list[dict]:
    """Reste à encaisser de chaque devis accepté, avec sa date attendue (rappel du patron, sinon échéance de facture)."""
    from app import tracking, unpaid
    from app.models import Invoice
    rows = []
    ov = tracking.overview(db)
    due_by_quote: dict[str, datetime] = {}
    for inv in db.query(Invoice).filter(Invoice.kind != "credit", Invoice.status.notin_(("draft", "cancelled")), Invoice.quotation_id.isnot(None)).all():
        d = unpaid.due_date(db, inv)
        if d and (inv.quotation_id not in due_by_quote or d > due_by_quote[inv.quotation_id]):
            due_by_quote[inv.quotation_id] = d
    for c in ov["chantiers"]:
        if c["reste"] <= 0:
            continue
        reminder = next((r for r in ov["rappels"] if r["numero"] == c["numero"]), None)
        when = (datetime.fromisoformat(reminder["date"]).replace(tzinfo=timezone.utc) if reminder else due_by_quote.get(c["id"]))
        state = "sans date" if when is None else "en retard" if _day(when) < _day(now) else "prévu"
        rows.append({"client": c["client"], "numero": c["numero"], "montant": round(c["reste"]), "date": when.date().isoformat() if when else None,
                     "etat": state, "source": "rappel" if reminder else "échéance facture" if when else ""})
    rows.sort(key=lambda r: (r["date"] is None, r["date"] or ""))
    return rows


def _fixed_out(cfg: dict, start: datetime, end: datetime) -> list[tuple[datetime, float, str]]:
    import calendar
    out, m = [], datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while m < end:
        last = calendar.monthrange(m.year, m.month)[1]
        for c in cfg["charges"]:
            d = m.replace(day=min(int(c["jour"]), last))
            if start <= d < end:
                out.append((d, float(c["montant"]), c["libelle"]))
        m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1, tzinfo=timezone.utc)
    return out


def forecast(db: Session, days: int = HORIZON_DAYS, now: datetime | None = None) -> dict:
    """Prévision semaine par semaine (prudent et probable), plus bas prévu, premier trou sous le seuil, et le détail."""
    from app import team
    now = now or _now()
    days = max(7, min(int(days or HORIZON_DAYS), 180))
    today = _day(now)
    end = today + timedelta(days=days)
    cfg = options(db)
    bal = current_balance(db, now)
    start_balance = bal["aujourdhui"] if bal else 0.0

    expected = _expected_in(db, now)
    ins_prudent = [(datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc), r["montant"]) for r in expected if r["etat"] == "prévu"]
    ins_probable = ins_prudent + [(today + timedelta(days=LATE_IN_DAYS), r["montant"]) for r in expected if r["etat"] == "en retard"] \
        + [(today + timedelta(days=UNDATED_IN_DAYS), r["montant"]) for r in expected if r["etat"] == "sans date"]

    workers_due = round(team.overview(db)["reste_du_total"])
    cash_out = _cash_out(db)
    planned = [(d, a, label) for d, a, label in cash_out if d > now and d < end]
    fixed = _fixed_out(cfg, now, end)
    past = [a for d, a, _ in cash_out if now - timedelta(days=AVERAGE_DAYS) <= d <= now]
    per_day = round(sum(past) / AVERAGE_DAYS, 2) if past else 0.0
    outs = [(today, float(workers_due), "reste dû aux ouvriers")] if workers_due > 0 else []
    outs += [(d, a, label) for d, a, label in planned + fixed]

    weeks, solde_p, solde_o = [], start_balance, start_balance
    low = {"prudent": (start_balance, today), "probable": (start_balance, today)}
    first_gap = None
    for i in range((days + 6) // 7):
        a, b = today + timedelta(days=7 * i), min(today + timedelta(days=7 * (i + 1)), end)
        span = (b - a).days
        out_w = sum(x for d, x, _ in outs if a <= _day(d) < b)
        avg_w = per_day * span
        in_p = sum(x for d, x in ins_prudent if a <= _day(d) < b)
        in_o = sum(x for d, x in ins_probable if a <= _day(d) < b)
        solde_p += in_p - out_w - avg_w
        solde_o += in_o - out_w
        weeks.append({"du": a.date().isoformat(), "au": (b - timedelta(days=1)).date().isoformat(),
                      "entrees_prudent": round(in_p), "entrees_probable": round(in_o), "sorties": round(out_w),
                      "depenses_courantes": round(avg_w), "solde_prudent": round(solde_p), "solde_probable": round(solde_o)})
        if solde_p < low["prudent"][0]:
            low["prudent"] = (solde_p, a)
        if solde_o < low["probable"][0]:
            low["probable"] = (solde_o, a)
        if first_gap is None and bal is not None and solde_p < cfg["seuil"]:
            first_gap = {"semaine_du": a.date().isoformat(), "solde": round(solde_p), "dans_jours": (a - today).days}

    attention: list[str] = []
    if bal is None:
        attention.append("Donne ton solde du moment (caisse + banque + Wave) pour voir ta vraie trésorerie : sans lui, seules les variations sont montrées.")
    if first_gap:
        attention.append(f"Trou de trésorerie prévu (prudent) la semaine du {first_gap['semaine_du'][8:10]}/{first_gap['semaine_du'][5:7]} : "
                         f"{_fmt(first_gap['solde'])} FCFA, sous ton seuil de {_fmt(cfg['seuil'])} FCFA.")
    late = [r for r in expected if r["etat"] == "en retard"]
    if late:
        attention.append(f"{len(late)} encaissement(s) en retard ({_fmt(sum(r['montant'] for r in late))} FCFA) : à relancer, ils ne comptent pas en prudent.")
    undated = [r for r in expected if r["etat"] == "sans date"]
    if undated:
        attention.append(f"{len(undated)} reste(s) à encaisser sans date ({_fmt(sum(r['montant'] for r in undated))} FCFA) : "
                         "fixe une date d'encaissement dans Encaissements pour une prévision plus juste.")
    return {
        "solde": bal, "seuil": cfg["seuil"], "horizon_jours": days, "semaines": weeks,
        "plus_bas": {k: {"solde": round(v[0]), "semaine_du": v[1].date().isoformat()} for k, v in low.items()},
        "premier_trou": first_gap,
        "entrees": expected, "sorties": {
            "ouvriers": workers_due,
            "charges_fixes": [{"date": d.date().isoformat(), "montant": round(a), "libelle": label} for d, a, label in sorted(fixed)],
            "prevues": [{"date": d.date().isoformat(), "montant": round(a), "libelle": label} for d, a, label in sorted(planned)],
            "courantes_par_jour": round(per_day)},
        "charges": cfg["charges"], "points_attention": attention,
        "note": ("Prévision calculée sans IA. Prudent : seulement l'argent attendu à une date à venir, dépenses courantes comptées au rythme "
                 "des 90 derniers jours. Probable : les retards rentrent dans 15 jours, les sans-date dans 30."),
    }


_checked_days: set[str] = set()


def daily_alert(db: Session, now: datetime | None = None) -> str:
    """Une seule vérification par jour (la surveillance tourne toutes les 5 minutes)."""
    day = (now or _now()).date().isoformat()
    if day in _checked_days:
        return ""
    _checked_days.add(day)
    return alert(db, now)


def alert(db: Session, now: datetime | None = None) -> str:
    """Message d'alerte si un trou est prévu (prudent) dans les 30 jours ; vide sinon, ou tant que le patron n'a pas donné son solde."""
    if options(db)["solde"] is None:
        return ""
    f = forecast(db, now=now)
    gap = f["premier_trou"]
    if not gap or gap["dans_jours"] > ALERT_DAYS:
        return ""
    return (f"Trésorerie : trou prévu dans {gap['dans_jours']} jours (semaine du {gap['semaine_du']}), solde prudent "
            f"{_fmt(gap['solde'])} FCFA sous le seuil de {_fmt(f['seuil'])} FCFA. Voir la page Trésorerie.")
