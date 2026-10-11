"""Bornes de saisie : une valeur impossible est refusée À L'ENTRÉE, avec sa raison.

Constat du diagnostic (octobre 2026) :
- `PUT /api/settings` acceptait `default_waste = -0,5`. Le moteur de calcul refuse une chute négative : TOUS les
  devis et calculs répondaient alors 500 « Erreur interne du serveur » — la fonction principale de l'appli cassée
  depuis l'écran de réglages, sans message utile.
- `/api/calc` renvoyait 500 au lieu de 400 pour une longueur négative, ce qui perdait le message du moteur
  (« « longueur » doit être un nombre strictement positif ») et gonflait le taux d'erreurs de la surveillance.
- `POST /api/materials/{id}/prices` acceptait un prix négatif ou nul, alors que la saisie en série les refuse :
  la promesse « aucun prix inventé » était contournable par une simple faute de frappe.
- Un client, un fournisseur, un matériau ou un projet pouvait être enregistré SANS NOM.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
os.environ.setdefault("UNIC_SECRET_KEY", "test-secret-key-not-for-prod")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------- réglages

def test_impossible_settings_are_refused(client):
    """Une chute négative, une plaque de 0 m, un entraxe nul, une TVA à 500 % : refusés à la saisie."""
    for body in ({"default_waste": -0.5}, {"default_waste": 0.9}, {"board_width_m": 0}, {"board_height_m": -2},
                 {"stud_spacing_m": 0}, {"vat_rate": 5}, {"vat_rate": -0.1}, {"default_margin": 150}):
        r = client.put("/api/settings", json=body)
        assert r.status_code == 422, f"{body} aurait dû être refusé (reçu {r.status_code})"
    chute = client.put("/api/settings", json={"default_waste": -0.5}).json()
    assert "default_waste" in str(chute), "le refus doit nommer le réglage fautif"


def test_real_settings_are_still_accepted(client):
    """Les valeurs métier normales passent : le refus ne doit pas gêner l'usage (TVA 18 %, chute 8 %, plaque 2,00 × 1,20)."""
    saved = client.get("/api/settings").json()
    try:
        r = client.put("/api/settings", json={"default_waste": 0.08, "vat_rate": 0.18, "board_width_m": 1.2,
                                              "board_height_m": 2.0, "stud_spacing_m": 0.6, "invoice_due_days": 30})
        assert r.status_code == 200, r.text
        assert r.json()["vat_rate"] == 0.18
    finally:   # la base de test est partagée : on remet les réglages d'origine
        client.put("/api/settings", json={k: v for k, v in saved.items()
                                          if k in ("default_waste", "vat_rate", "board_width_m", "board_height_m",
                                                   "stud_spacing_m", "invoice_due_days") and v is not None})


def test_a_bad_setting_never_breaks_the_calculator(client):
    """Après un refus (chute -50 %), le devis se calcule encore : le moteur n'est jamais mis dans un état impossible."""
    assert client.put("/api/settings", json={"default_waste": -0.5}).status_code == 422
    r = client.post("/api/calc", json={"kind": "partition", "length_m": 10, "height_m": 2.5})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- calculs

def test_impossible_calculation_answers_400_with_the_reason(client):
    """Une longueur négative ou nulle : 400 et la raison du moteur, jamais 500 « erreur interne »."""
    for body in ({"kind": "partition", "length_m": -5, "height_m": 2.5},
                 {"kind": "partition", "length_m": 0, "height_m": 2.5},
                 {"kind": "partition", "length_m": 1e300, "height_m": 1e300},
                 {"kind": "ceiling", "length_m": -1, "width_m": 2}):
        r = client.post("/api/calc", json=body)
        assert r.status_code == 400, f"{body} -> {r.status_code} {r.text[:120]}"
        detail = str(r.json().get("detail") or "")
        assert "nombre strictement positif" in detail or "au-delà de" in detail, detail


def test_normal_calculation_still_works(client):
    """320 m × 2,50 m, deux faces = 1 600 m² : le calcul de référence reste exact."""
    r = client.post("/api/calc", json={"kind": "partition", "length_m": 320, "height_m": 2.5, "sides": 2})
    assert r.status_code == 200, r.text
    assert "1 600" in r.text or "1600" in r.text


# ---------------------------------------------------------------- prix

def test_price_must_be_positive(client):
    """Un prix nul ou négatif est refusé : la même règle que la saisie en série des prix."""
    sku = f"TEST-BORNE-{uuid.uuid4().hex[:8]}"   # référence unique : la base de test est conservée entre deux exécutions
    r = client.post("/api/materials", json={"sku": sku, "name": "Article de test", "category": "test", "unit": "u"})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    for amount in (-5000, 0):
        r = client.post(f"/api/materials/{mid}/prices", json={"kind": "selling", "amount": amount})
        assert r.status_code == 422, f"prix {amount} accepté ({r.status_code})"
    assert client.post(f"/api/materials/{mid}/prices", json={"kind": "selling", "amount": 8500}).status_code == 200


# ---------------------------------------------------------------- fiches sans nom

def test_a_record_can_never_be_saved_without_a_name(client):
    """Client, fournisseur, matériau, projet : le nom est obligatoire (jamais une ligne vide dans l'appli)."""
    assert client.post("/api/customers", json={"name": ""}).status_code == 422
    assert client.post("/api/customers", json={"name": "   "}).status_code == 422
    assert client.post("/api/suppliers", json={"name": ""}).status_code == 422
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/materials", json={"sku": "", "name": "Test", "category": "c", "unit": "u"}).status_code == 422
    assert client.post("/api/materials", json={"sku": f"TEST-BORNE-{uuid.uuid4().hex[:8]}", "name": "", "category": "c", "unit": "u"}).status_code == 422


def test_a_valid_name_is_kept_but_trimmed(client):
    r = client.post("/api/customers", json={"name": "  Awa Fall  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Awa Fall"


# ---------------------------------------------------------------- accès local (garde du code d'accès)

def _request(host: str, headers: dict | None = None):
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/api/customers", "client": (host, 12345),
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "query_string": b"", "server": ("test", 80), "scheme": "http"}
    return Request(scope)


def test_local_access_is_refused_when_the_call_went_through_a_proxy():
    """Sans code d'accès, l'exception « même machine » ne doit pas s'appliquer derrière un relais.

    Un proxy installé sur la même machine (nginx, Caddy, routeur d'hébergeur) fait arriver TOUTES les requêtes
    d'Internet depuis 127.0.0.1 : l'exception ouvrait alors l'API entière (clients, devis, factures) sur Internet.
    """
    from app.main import _is_loopback
    assert _is_loopback(_request("127.0.0.1")) is True                      # vrai usage local, en direct
    assert _is_loopback(_request("127.0.0.1", {"x-forwarded-for": "41.82.0.1"})) is False
    assert _is_loopback(_request("127.0.0.1", {"x-real-ip": "41.82.0.1"})) is False
    assert _is_loopback(_request("127.0.0.1", {"forwarded": "for=41.82.0.1"})) is False
    assert _is_loopback(_request("41.82.0.1")) is False                     # venu d'Internet


def test_cors_never_falls_back_to_wildcard_with_credentials(monkeypatch):
    """En production sans ALLOWED_ORIGINS : aucune origine externe (et jamais « * » avec les identifiants).

    Le repli « * » s'appliquait même en production ; avec `allow_credentials=True`, Starlette renvoie alors
    l'origine de l'appelant : n'importe quel site pouvait appeler l'API depuis un navigateur.
    """
    from app import main
    monkeypatch.setattr(main.settings, "allowed_origins", "")
    monkeypatch.setattr(main.settings, "unic_env", "production")
    assert main._origins() == []                       # aucune origine WEB externe déclarée
    assert main._cors_origins() == list(main.NATIVE_ORIGINS)   # mais les applis installées passent toujours
    monkeypatch.setattr(main.settings, "unic_env", "development")
    assert main._cors_origins() == ["*"]               # en développement, le confort du poste de travail reste
    # une origine déclarée est respectée, sans perdre les applications installées
    monkeypatch.setattr(main.settings, "unic_env", "production")
    monkeypatch.setattr(main.settings, "allowed_origins", "https://ia.unicplaquiste.com")
    assert main._cors_origins()[0] == "https://ia.unicplaquiste.com"
    assert "https://localhost" in main._cors_origins()

    cors = [m for m in main.app.user_middleware if getattr(m.cls, "__name__", "") == "CORSMiddleware"]
    assert cors, "CORS absent de l'application"
    kwargs = cors[0].kwargs
    assert kwargs.get("allow_origins") == main._CORS_ORIGINS, "la liste du middleware doit venir de _origins(), sans repli"
    # L'appli n'utilise aucun cookie : les identifiants ne doivent jamais être autorisés (sinon Starlette
    # renvoie l'origine de l'appelant, et n'importe quel site peut appeler l'API depuis un navigateur).
    assert kwargs.get("allow_credentials") is not True, "allow_credentials ne doit pas être activé"


# ---------------------------------------------------------------- bulle du site public (autre domaine)

def test_public_widget_stays_reachable_from_any_website(client):
    """La bulle du site (`/api/public/chat`) est appelée depuis un autre domaine : elle doit répondre.

    Les routes publiques ne portent aucune donnée de l'entreprise et sont limitées par visiteur ; elles restent
    ouvertes à toute origine, sans identifiants. Les routes privées, elles, gardent la liste stricte.
    """
    preflight = client.options("/api/public/chat", headers={"Origin": "https://unicplaquiste.com",
                                                           "Access-Control-Request-Method": "POST",
                                                           "Access-Control-Request-Headers": "content-type"})
    assert preflight.status_code == 204, preflight.text
    assert preflight.headers.get("access-control-allow-origin") == "*"
    assert "content-type" in preflight.headers.get("access-control-allow-headers", "")
    assert not preflight.headers.get("access-control-allow-credentials"), "jamais d'identifiants sur le public"


def test_private_routes_are_not_opened_by_the_public_widget():
    """Le middleware du public ne touche QUE les routes publiques : aucune en-tête ajoutée aux routes privées."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient as MiniClient

    from app.main import _PublicCors

    mini = FastAPI()

    @mini.get("/api/customers")
    def _private():
        return {"ok": True}

    @mini.post("/api/public/chat")
    def _public():
        return {"reply": "bonjour"}

    mini.add_middleware(_PublicCors)
    c = MiniClient(mini)
    assert "access-control-allow-origin" not in c.get("/api/customers", headers={"Origin": "https://x.example"}).headers
    assert c.post("/api/public/chat", headers={"Origin": "https://x.example"}).headers["access-control-allow-origin"] == "*"


# ---------------------------------------------------------------- politique de sécurité du contenu


def _html_headers(client):
    """En-têtes d'une page HTML (la page de documentation du serveur : toujours présente, sans dépendre de l'interface compilée)."""
    r = client.get("/docs")
    assert r.headers["content-type"].startswith("text/html")
    return r.headers


def test_csp_is_only_on_html_documents_never_on_pdf_or_json(client):
    """Pas de politique sur un PDF ou une réponse JSON : `object-src 'none'` peut empêcher le lecteur PDF du navigateur de l'afficher."""
    assert "content-security-policy" not in client.get("/api/ping").headers
    assert "content-security-policy-report-only" not in client.get("/api/ping").headers
    assert "content-security-policy" in _html_headers(client)

def test_content_security_policy_is_enforced(client):
    """La politique appliquée bloque l'injection de script sans pouvoir casser l'interface.

    L'interface ne contient aucun script en ligne : `script-src 'self'` suffit, et surtout n'autorise NI
    `'unsafe-inline'` NI `'unsafe-eval'`. Rien n'utilise <object>/<embed>, base ou formulaire externe.
    """
    h = _html_headers(client)
    csp = h.get("content-security-policy")
    assert csp, "la politique de sécurité du contenu doit être envoyée sur les pages HTML"
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0], "pas de script en ligne autorisé"
    assert "unsafe-eval" not in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_wider_policy_is_only_measured(client):
    """La politique large part en « report-only » : mesurée, pas appliquée (aucune régression d'affichage possible)."""
    h = _html_headers(client)
    report = h.get("content-security-policy-report-only")
    assert report and "default-src 'self'" in report
    assert "connect-src 'self'" in report
    assert "blob:" in report          # aperçus de PDF, photos et lectures vocales


# ---------------------------------------------------------------- route d'API inconnue = 404, jamais 200

def test_unknown_api_route_is_404_not_a_fake_success(client):
    """Avant : GET /api/inexistant répondait 200 {"detail": "Not Found"} ; l'interface le prenait pour un succès."""
    for path in ("/api/inexistant", "/api/files/zzz-inconnu-xyz", "/api/customers/n-existe-pas/zzz"):
        r = client.get(path)
        assert r.status_code in (404, 405, 401), (path, r.status_code)
        assert r.status_code != 200, path
    r = client.get("/api/inexistant")
    assert r.headers["content-type"].startswith("application/json") and r.json() == {"detail": "Not Found"}
    # l'interface (pages sans « /api ») continue de se charger même sur une adresse inconnue
    assert client.get("/une-page-qui-nexiste-pas").status_code == 200


def test_upload_filename_cannot_escape_the_storage_folder(client, tmp_path):
    """Noms de fichiers hostiles (../, \\, absolu, octet nul) : le fichier est rangé sous un identifiant, jamais hors du dossier de stockage."""
    from app.config import settings
    root = settings.storage_path.resolve()
    for name in ("../../../../tmp/evil_upload.txt", "..\\..\\evil2.txt", "/etc/evil3.txt", "a/../../b.txt", "x\x00.txt"):
        r = client.post("/api/files", files={"file": (name, b"hello", "text/plain")})
        assert r.status_code == 200, (name, r.status_code)
        from app.database import SessionLocal
        from app.models import StoredFile
        db = SessionLocal()
        try:
            rec = db.get(StoredFile, r.json()["id"])
            assert Path(rec.path).resolve().is_relative_to(root), (name, rec.path)
            assert ".." not in Path(rec.path).name and "/" not in Path(rec.path).name
        finally:
            db.close()
