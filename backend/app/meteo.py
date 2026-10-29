"""Météo de chantier (Open-Meteo : gratuit, sans clé, données réelles) : maintenant et jusqu'à 7 jours, pour une ville ou un chantier.

Seul le nom du lieu part vers Open-Meteo. Les conseils de chantier (livraison et stockage des plaques, séchage des bandes et de
l'enduit, manutention par vent fort) sont tirés des chiffres ici, en code, par des seuils écrits ci-dessous : l'IA les cite, elle
ne les invente pas.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

logger = logging.getLogger("unic.meteo")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT = {"nom": "Dakar", "pays": "Sénégal", "lat": 14.6937, "lon": -17.4441}
CACHE_S = 900            # un même lieu n'est redemandé qu'au bout de 15 min
TIMEOUT_S = 8.0

# Seuils des conseils (prudents, généraux) : la pose et les joints craignent l'eau, l'air saturé et la chaleur ; les plaques, le vent.
PLUIE_MM = 1.0           # pluie prévue dans la journée
PLUIE_PROBA = 60         # ou probabilité de pluie (%)
HUMIDE = 80              # humidité moyenne (%) : bandes et enduit sèchent lentement
VENT_KMH = 40            # rafales / vent max : plaques difficiles à porter dehors
CHALEUR = 35             # °C : l'enduit tire vite

_CIEL = [((0,), "ciel clair"), ((1,), "peu nuageux"), ((2,), "partiellement nuageux"), ((3,), "couvert"), ((45, 48), "brouillard"),
         ((51, 53, 55, 56, 57), "bruine"), ((61, 63, 65, 66, 67), "pluie"), ((71, 73, 75, 77, 85, 86), "neige"),
         ((80, 81, 82), "averses"), ((95, 96, 99), "orage")]
_cache: dict[tuple, tuple[float, dict]] = {}
_places: dict[str, dict] = {}   # lieux déjà trouvés : un nom n'est géocodé qu'une fois
_lock = threading.Lock()


def ciel(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "inconnu"
    return next((label for codes, label in _CIEL if c in codes), "inconnu")


def _get(url: str, params: dict) -> dict:
    """Appel Open-Meteo ; un refus passager (trop de demandes, coupure réseau, serveur occupé) est retenté UNE fois après 1 s."""
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=TIMEOUT_S) as c:
                r = c.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            passing = isinstance(exc, httpx.TransportError) or exc.response.status_code in (429, 500, 502, 503, 504)
            if attempt == 2 or not passing:
                raise
            time.sleep(1.0)
    raise RuntimeError("inaccessible")   # pour le typage : la boucle rend ou lève toujours


def lieu(nom: str) -> dict | None:
    """Ville ou lieu → coordonnées (Sénégal d'abord, puis le monde). None si introuvable."""
    key = " ".join(nom.lower().split())
    if key in _places:
        return _places[key]
    for extra in ({"countryCode": "SN"}, {}):
        data = _get(GEO_URL, {"name": nom, "count": 1, "language": "fr", "format": "json", **extra})
        hit = (data.get("results") or [None])[0]
        if hit:
            _places[key] = {"nom": hit.get("name") or nom, "pays": hit.get("country") or "", "lat": hit["latitude"], "lon": hit["longitude"]}
            return _places[key]
    return None


def conseils(jours: list[dict]) -> list[str]:
    """Conseils de chantier tirés des chiffres (code, seuils ci-dessus). Une ligne par jour concerné et par risque."""
    out: list[str] = []
    for j in jours:
        d = j["date"]
        if (j.get("pluie_mm") or 0) >= PLUIE_MM or (j.get("proba_pluie") or 0) >= PLUIE_PROBA:
            out.append(f"{d} : pluie prévue ({j.get('pluie_mm') or 0:g} mm, {j.get('proba_pluie') or 0} %) — livraison de plaques bâchée, "
                       "stockage à plat et à l'abri, pas de pose dans une zone encore ouverte.")
        if (j.get("humidite") or 0) >= HUMIDE:
            out.append(f"{d} : air très humide ({j['humidite']} %) — bandes et enduit sèchent plus lentement : attendre le séchage complet "
                       "avant de poncer ou de peindre.")
        if (j.get("vent_max") or 0) >= VENT_KMH:
            out.append(f"{d} : vent fort ({j['vent_max']:g} km/h) — prudence au transport et à la manutention des plaques dehors.")
        if (j.get("tmax") or 0) >= CHALEUR:
            out.append(f"{d} : forte chaleur ({j['tmax']:g} °C) — l'enduit tire vite : gâcher par petites quantités.")
    return out


def prevision(nom: str = "", jours: int = 3, defaut: str = "") -> dict:
    """Météo réelle d'un lieu (nom vide : `defaut`, la ville de l'entreprise, sinon Dakar). {'error': …} si le service ne répond pas."""
    jours = max(1, min(7, int(jours or 3)))
    wanted = (nom or defaut or "").strip()
    try:
        place = lieu(wanted) if wanted and wanted.lower() != "dakar" else DEFAULT
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Géocodage Open-Meteo impossible : %s", exc)
        return {"error": "Météo indisponible pour l'instant (service Open-Meteo injoignable). Réessaie dans un moment."}
    if place is None:
        return {"error": f"Lieu « {wanted} » introuvable. Donne la ville la plus proche du chantier."}
    key = (round(place["lat"], 3), round(place["lon"], 3), jours)
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_S:
            return hit[1]
    try:
        data = _get(FORECAST_URL, {
            "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": jours, "wind_speed_unit": "kmh",
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                     "wind_speed_10m_max,relative_humidity_2m_mean"})
        cur, day = data.get("current") or {}, data.get("daily") or {}
        days = [{"date": d, "ciel": ciel(day["weather_code"][i]), "tmin": day["temperature_2m_min"][i], "tmax": day["temperature_2m_max"][i],
                 "pluie_mm": day["precipitation_sum"][i], "proba_pluie": (day.get("precipitation_probability_max") or [None] * len(day["time"]))[i],
                 "vent_max": day["wind_speed_10m_max"][i], "humidite": (day.get("relative_humidity_2m_mean") or [None] * len(day["time"]))[i]}
                for i, d in enumerate(day.get("time") or [])]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Prévision Open-Meteo impossible : %s", exc)
        return {"error": "Météo indisponible pour l'instant (service Open-Meteo injoignable). Réessaie dans un moment."}
    out = {
        "lieu": ", ".join(x for x in (place["nom"], place["pays"]) if x),
        "maintenant": {"heure": cur.get("time"), "ciel": ciel(cur.get("weather_code")), "temperature": cur.get("temperature_2m"),
                       "humidite": cur.get("relative_humidity_2m"), "pluie_mm": cur.get("precipitation"), "vent": cur.get("wind_speed_10m")},
        "jours": days,
        "conseils_chantier": conseils(days),
        "unites": "°C, %, mm, km/h",
        "source": "Open-Meteo (open-meteo.com), prévision du jour",
    }
    with _lock:
        _cache[key] = (time.monotonic(), out)
    return out
