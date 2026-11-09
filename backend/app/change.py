"""Taux de change réels pour les achats et les offres à l'étranger (jamais devinés).

Franc CFA (XOF) ↔ euro : parité FIXE officielle (BCEAO), 1 € = 655,957 FCFA, sans réseau.
Autres monnaies (dollar, yuan, livre…) : taux de référence du jour de la Banque centrale européenne via Frankfurter
(gratuit, sans clé, trouvé dans le catalogue public-apis), puis passage par l'euro. Seuls les codes de monnaie partent sur le réseau.
Un taux de référence est indicatif : la banque ou le bureau de change ajoute sa marge, et l'outil le dit.
"""
from __future__ import annotations

import logging
import threading
import time
from decimal import ROUND_HALF_UP, Decimal

import httpx

logger = logging.getLogger("unic.change")

XOF_PER_EUR = Decimal("655.957")      # parité fixe franc CFA / euro (BCEAO, depuis 1999)
RATES_URL = "https://api.frankfurter.dev/v1/latest"
CACHE_S = 3600                        # la BCE publie une fois par jour ouvré : une heure de cache suffit
TIMEOUT_S = 8.0
SOURCE_BCE = "Banque centrale européenne (taux de référence du jour) via Frankfurter (frankfurter.dev)"
SOURCE_FIXE = "parité fixe officielle BCEAO : 1 € = 655,957 FCFA"

ALIASES = {
    "FCFA": "XOF", "F CFA": "XOF", "CFA": "XOF", "XOF": "XOF", "FRANC CFA": "XOF", "FRANCS CFA": "XOF",
    "EUR": "EUR", "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "USD": "USD", "$": "USD", "DOLLAR": "USD", "DOLLARS": "USD",
    "CNY": "CNY", "YUAN": "CNY", "YUANS": "CNY", "RMB": "CNY",
    "GBP": "GBP", "£": "GBP", "LIVRE": "GBP", "LIVRES": "GBP",
}

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def code(monnaie: str) -> str:
    """« dollars », « fcfa », « usd »… → code à 3 lettres (majuscules). Une chaîne vide ou bizarre reste telle quelle (refusée plus loin)."""
    m = " ".join((monnaie or "").upper().replace(".", "").split())
    return ALIASES.get(m, m)


def _get(params: dict) -> dict:
    """Appel Frankfurter ; un refus passager (trop de demandes, coupure, serveur occupé) est retenté UNE fois après 1 s."""
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True) as c:
                r = c.get(RATES_URL, params=params)
                r.raise_for_status()
                return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            passing = isinstance(exc, httpx.TransportError) or exc.response.status_code in (429, 500, 502, 503, 504)
            if attempt == 2 or not passing:
                raise
            time.sleep(1.0)
    raise RuntimeError("inaccessible")   # pour le typage : la boucle rend ou lève toujours


def _per_eur(cur: str) -> tuple[Decimal, str, str]:
    """Combien de `cur` pour 1 € → (taux, date du taux, source). XOF et EUR sans réseau ; le reste via la BCE (cache 1 h)."""
    if cur == "EUR":
        return Decimal(1), "", SOURCE_FIXE
    if cur == "XOF":
        return XOF_PER_EUR, "", SOURCE_FIXE
    with _lock:
        hit = _cache.get(cur)
        if hit and time.monotonic() - hit[0] < CACHE_S:
            data = hit[1]
            return Decimal(str(data["rates"][cur])), data.get("date", ""), SOURCE_BCE
    data = _get({"base": "EUR", "symbols": cur})
    rate = (data.get("rates") or {}).get(cur)
    if not rate:
        raise KeyError(cur)
    with _lock:
        _cache[cur] = (time.monotonic(), data)
    return Decimal(str(rate)), data.get("date", ""), SOURCE_BCE


def _arrondi(v: Decimal, cur: str) -> float:
    """Le franc CFA n'a pas de centimes : arrondi à l'unité. Les autres monnaies : au centime."""
    step = Decimal(1) if cur == "XOF" else Decimal("0.01")
    return float(v.quantize(step, rounding=ROUND_HALF_UP))


def convertir(montant, de: str, vers: str = "FCFA") -> dict:
    """Convertit `montant` de la monnaie `de` vers `vers` (FCFA par défaut). {'error': …} si monnaie inconnue ou service muet."""
    try:
        m = Decimal(str(montant).replace(" ", "").replace(",", "."))
    except ArithmeticError:
        return {"error": f"Montant « {montant} » illisible : donne un nombre, ex. 1500 ou 1500,50."}
    if not m.is_finite() or m < 0:
        return {"error": "Le montant doit être un nombre positif."}
    a, b = code(de), code(vers)
    if len(a) != 3 or len(b) != 3 or not a.isalpha() or not b.isalpha():
        return {"error": f"Monnaie inconnue (« {de} » → « {vers} ») : donne un code à 3 lettres (USD, EUR, CNY, GBP, XOF…)."}
    try:
        ra, da, sa = _per_eur(a)
        rb, db, sb = _per_eur(b)
    except KeyError as exc:
        return {"error": f"Monnaie « {exc.args[0]} » non publiée par la BCE : je n'ai pas de taux fiable pour elle."}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Taux de change indisponible : %s", exc)
        return {"error": "Taux de change indisponible pour l'instant (service de la BCE injoignable). Réessaie dans un moment."}
    taux = rb / ra                               # combien de `b` pour 1 `a`
    sources = list(dict.fromkeys(s for s in (sa, sb) if s))
    out = {
        "montant": float(m), "de": a, "vers": b,
        "resultat": _arrondi(m * taux, b),
        "taux": f"1 {a} = {float(taux):.6g} {b}",
        "date_du_taux": da or db or "parité fixe",
        "source": " ; ".join(sources),
    }
    if SOURCE_BCE in sources:
        out["note"] = ("Taux de référence indicatif : la banque, Wave/Orange Money ou le bureau de change ajoute sa marge. "
                       "Pour un achat, demande le taux exact au moment du paiement.")
    return out
