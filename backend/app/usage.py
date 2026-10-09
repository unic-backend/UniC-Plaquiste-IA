"""Compteur de coût Claude : tokens réels renvoyés par l'API x tarif public. Estimation, pas la facture.

Tarifs (USD par million de jetons) : Sonnet 5.5 = 2 / 10 ; Opus 5.5 = 4 / 20 ; lecture de cache 0,20 ;
écriture de cache = 1,25 x l'entrée ; recherche Internet = 10 $ les 1 000. Un modèle inconnu est chiffré
au tarif Sonnet et marqué « tarif inconnu » : jamais présenté comme exact.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AppSetting, UsageLog

PRICES = {  # entrée, sortie, lecture de cache
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
}
# Tarifs Vibecode (https://vibecode.moe/models, canal « cheap » au 09/10/2026) : indicatifs — le canal
# « stable » et les heures de pointe (peak) sont plus chers ; la facture exacte est sur vibecode.moe.
VIBECODE_PRICES = {  # entrée, sortie, lecture de cache
    "claude-sonnet-5-5": (0.20, 0.98, 0.020),
    "claude-opus-5-5": (0.39, 1.97, 0.020),
    "claude-haiku-4-5": (0.20, 0.98, 0.020),
}
DEFAULT_PRICE = PRICES["claude-sonnet-5-5"]
WEB_SEARCH_USD = 10.0 / 1000   # outil serveur web_search : spécifique à Anthropic (pas de tel champ chez Vibecode)

#: remplie par le fournisseur Claude pendant un appel (une entrée par échange avec l'API)
TALLY: ContextVar[list | None] = ContextVar("claude_usage_tally", default=None)


def tally(resp) -> None:
    sink = TALLY.get()
    u = getattr(resp, "usage", None)
    if sink is None or u is None:
        return
    st = getattr(u, "server_tool_use", None)
    sink.append({
        "input": int(getattr(u, "input_tokens", 0) or 0), "output": int(getattr(u, "output_tokens", 0) or 0),
        "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "cache_write": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        "web": int(getattr(st, "web_search_requests", 0) or 0) if st is not None else 0,
    })


def cost_of(model: str, rows: list[dict], provider: str = "claude") -> tuple[dict, float, bool]:
    """provider « claude » = tarifs publics Anthropic ; « vibecode » = tarifs du relais (indicatifs)."""
    table = PRICES if provider == "claude" else VIBECODE_PRICES if provider == "vibecode" else {}
    known = model in table
    p_in, p_out, p_cache = table.get(model, DEFAULT_PRICE)
    total = {k: sum(r[k] for r in rows) for k in ("input", "output", "cache_read", "cache_write", "web")}
    usd = (total["input"] * p_in + total["output"] * p_out + total["cache_read"] * p_cache
           + total["cache_write"] * p_in * 1.25) / 1_000_000 + total["web"] * WEB_SEARCH_USD
    return total, round(usd, 6), known


def record(db: Session, rows: list[dict] | None, model: str, provider: str = "claude") -> None:
    if not rows:
        return
    total, usd, known = cost_of(model, rows, provider=provider)
    db.add(UsageLog(model=model, input_tokens=total["input"], output_tokens=total["output"],
                    cache_read_tokens=total["cache_read"], cache_write_tokens=total["cache_write"],
                    web_searches=total["web"], cost_usd=usd, price_known=known))


def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def set_budget(db: Session, amount_usd: float) -> None:
    for key, val in (("credit_usd", f"{amount_usd:.4f}"), ("credit_since", datetime.now(timezone.utc).isoformat())):
        row = db.get(AppSetting, key)
        if row:
            row.value = val
        else:
            db.add(AppSetting(key=key, value=val))
    db.commit()


def _sum(db: Session, since: datetime | None = None) -> tuple[float, int]:
    q = db.query(func.coalesce(func.sum(UsageLog.cost_usd), 0.0), func.count(UsageLog.id))
    if since is not None:
        q = q.filter(UsageLog.created_at >= since)
    usd, n = q.one()
    return float(usd or 0.0), int(n or 0)


def summary(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today, n_today = _sum(db, day0)
    week, _ = _sum(db, day0 - timedelta(days=6))
    month, n_month = _sum(db, day0.replace(day=1))
    total, n_total = _sum(db)
    models = [{"model": m, "messages": n, "cout_usd": round(float(c or 0), 4)} for m, n, c in
              db.query(UsageLog.model, func.count(UsageLog.id), func.sum(UsageLog.cost_usd)).group_by(UsageLog.model).all()]
    days = []
    for i in range(13, -1, -1):
        start = day0 - timedelta(days=i)
        usd = db.query(func.coalesce(func.sum(UsageLog.cost_usd), 0.0)).filter(
            UsageLog.created_at >= start, UsageLog.created_at < start + timedelta(days=1)).scalar()
        days.append({"jour": start.date().isoformat(), "cout_usd": round(float(usd or 0), 4)})
    credit = _get(db, "credit_usd")
    since = _get(db, "credit_since")
    left = None
    if credit:
        try:
            since_dt = datetime.fromisoformat(since) if since else None
        except ValueError:
            since_dt = None
        spent, _ = _sum(db, since_dt)
        left = round(float(credit) - spent, 4)
    avg = round(total / n_total, 4) if n_total else 0.0
    return {
        "aujourdhui_usd": round(today, 4), "semaine_usd": round(week, 4), "mois_usd": round(month, 4),
        "total_usd": round(total, 4), "messages_aujourdhui": n_today, "messages_mois": n_month, "messages_total": n_total,
        "moyenne_par_message_usd": avg, "par_modele": models, "jours": days,
        "credit_usd": float(credit) if credit else None, "credit_depuis": since or None, "reste_usd": left,
        "messages_restants_estimes": int(left / avg) if (left and avg and left > 0) else None,
        "tarif_inconnu": bool(db.query(UsageLog).filter(UsageLog.price_known.is_(False)).first()),
        "avertissement": ("Estimation au tarif public Anthropic (jetons réels x prix). La facture exacte est sur "
                          "console.anthropic.com › Usage ; le solde exact aussi."),
    }
