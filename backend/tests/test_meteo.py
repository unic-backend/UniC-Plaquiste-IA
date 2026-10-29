"""Météo de chantier (brique reprise de ming-voice, adaptée au métier) : données réelles Open-Meteo, conseils de chantier calculés
en code par des seuils écrits, lieu par défaut = ville de l'entreprise. Le service est simulé ici (pas de réseau dans les tests)."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import meteo
from app.agent import AgentSession
from app.database import SessionLocal
from app.main import app

FORECAST = {
    "current": {"time": "2026-10-29T18:00", "temperature_2m": 29.4, "relative_humidity_2m": 78, "precipitation": 0.0,
                "wind_speed_10m": 14.2, "weather_code": 2},
    "daily": {"time": ["2026-10-29", "2026-10-30", "2026-10-31"], "weather_code": [2, 63, 95],
              "temperature_2m_min": [24.1, 23.8, 25.0], "temperature_2m_max": [31.0, 29.5, 36.2],
              "precipitation_sum": [0.0, 12.4, 3.1], "precipitation_probability_max": [10, 85, 70],
              "wind_speed_10m_max": [18.0, 22.0, 45.5], "relative_humidity_2m_mean": [70, 88, 75]},
}


@pytest.fixture(autouse=True)
def _vide_le_cache():
    meteo._cache.clear()
    meteo._places.clear()
    yield
    meteo._cache.clear()
    meteo._places.clear()


def _fake(calls: list, geo: dict | None = None):
    def get(url, params):
        calls.append((url, dict(params)))
        if url == meteo.GEO_URL:
            return geo if geo is not None else {"results": [{"name": "Thiès", "country": "Sénégal", "latitude": 14.79, "longitude": -16.93}]}
        return FORECAST
    return get


def test_prevision_reelle_et_conseils_de_chantier(monkeypatch):
    calls: list = []
    monkeypatch.setattr(meteo, "_get", _fake(calls))
    out = meteo.prevision("Thiès", 3)
    assert out["lieu"] == "Thiès, Sénégal" and out["source"].startswith("Open-Meteo")
    assert out["maintenant"] == {"heure": "2026-10-29T18:00", "ciel": "partiellement nuageux", "temperature": 29.4, "humidite": 78,
                                 "pluie_mm": 0.0, "vent": 14.2}
    assert [d["ciel"] for d in out["jours"]] == ["partiellement nuageux", "pluie", "orage"]
    c = out["conseils_chantier"]
    assert len(c) == 5                                                  # 30/10 : pluie + humidité ; 31/10 : pluie (70 %), vent, chaleur
    assert c[0].startswith("2026-10-30 : pluie prévue (12.4 mm, 85 %)") and "bâchée" in c[0]
    assert c[1].startswith("2026-10-30 : air très humide (88 %)")
    assert any(x.startswith("2026-10-31 : vent fort (45.5 km/h)") for x in c)
    assert any(x.startswith("2026-10-31 : forte chaleur (36.2 °C)") for x in c)
    assert not any(x.startswith("2026-10-29") for x in c)               # beau temps : aucun conseil inventé
    geo, fc = calls
    assert geo[1]["name"] == "Thiès" and geo[1]["countryCode"] == "SN"   # Sénégal d'abord
    assert fc[1]["latitude"] == 14.79 and fc[1]["forecast_days"] == 3
    meteo.prevision("Thiès", 3)
    assert len(calls) == 2                                              # 15 min de cache : pas de nouvel appel


def test_dakar_par_defaut_sans_geocodage_et_lieu_inconnu(monkeypatch):
    calls: list = []
    monkeypatch.setattr(meteo, "_get", _fake(calls, geo={"results": []}))
    out = meteo.prevision("", 9)
    assert out["lieu"] == "Dakar, Sénégal" and [u for u, _ in calls] == [meteo.FORECAST_URL] and calls[0][1]["forecast_days"] == 7
    bad = meteo.prevision("Zzzville")
    assert "introuvable" in bad["error"] and [p.get("countryCode") for u, p in calls if u == meteo.GEO_URL] == ["SN", None]


def test_service_injoignable_dit_clairement(monkeypatch):
    def down(url, params):
        raise httpx.ConnectError("réseau coupé")
    monkeypatch.setattr(meteo, "_get", down)
    assert "indisponible" in meteo.prevision("Dakar")["error"]
    assert "indisponible" in meteo.prevision("Thiès")["error"]


def test_outil_weather_prend_la_ville_de_l_entreprise(monkeypatch):
    seen = {}
    monkeypatch.setattr(meteo, "prevision", lambda lieu, jours, defaut="": seen.update(lieu=lieu, jours=jours, defaut=defaut) or {"lieu": "x"})
    monkeypatch.setattr("app.agent.company_dict", lambda db: {"name": "UniC", "city": "Rufisque"})
    with TestClient(app), SessionLocal() as db:
        out = AgentSession(db, None, {})("weather", {"jours": 2})
    assert out["lieu"] == "x" and seen == {"lieu": "", "jours": 2, "defaut": "Rufisque"}


def test_seuils_et_codes_du_ciel():
    assert meteo.ciel(0) == "ciel clair" and meteo.ciel("81") == "averses" and meteo.ciel(None) == "inconnu"
    assert meteo.conseils([{"date": "d", "pluie_mm": 0.9, "proba_pluie": 59, "humidite": 79, "vent_max": 39.9, "tmax": 34.9}]) == []
