from __future__ import annotations

import logging
import secrets
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import router
from app.api_field import router as field_router
from app.api_reseaux import router as reseaux_router
from app.api_voice import router as voice_router
from app.api_website import router as website_router
from app import ratelimit
from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_columns, ensure_indexes
from app.seed import seed_if_empty

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await run_in_threadpool(startup)
    yield
    logger.info("Arrêt propre : fermeture des connexions à la base")
    engine.dispose()


app = FastAPI(
    lifespan=lifespan,
    title="UniC AI",
    description="Plateforme métier UniC Plaquiste — pas un assistant généraliste.",
    version=__version__,
)

logger = logging.getLogger("unic.main")
_MAX_FAILS, _WINDOW = 10, 600.0


def _token_ok(given: str) -> bool:
    """Jeton de connexion e-mail + mot de passe (même en-tête que le code d'accès)."""
    if not given.startswith("uat_"):
        return False
    from app import auth
    db = SessionLocal()
    try:
        return auth.token_valid(db, given)
    except Exception:
        return False
    finally:
        db.close()


@app.middleware("http")
async def access_code_guard(request: Request, call_next):
    """Code d'accès unique sur /api/*. Ajouté AVANT le CORS : le 401 garde ses en-têtes CORS."""
    code = settings.unic_access_code
    path = request.url.path
    if not code and settings.unic_env == "production" and _protected(path, request.method) and not _is_loopback(request):
        # Fermé par défaut : sans code, l'API serait ouverte à tout Internet (devis, factures, mot de passe…).
        logger.error("UNIC_ACCESS_CODE absent en production : accès refusé à %s", path)
        return JSONResponse({"detail": "Serveur non sécurisé : définis UNIC_ACCESS_CODE (Render › Environment)."}, status_code=503)
    if code and path.startswith("/api/") and path not in ("/api/ping", "/api/linkedin/callback", "/api/instagram/callback",
                                                          "/api/auth/login", "/api/auth/status", "/api/health/live", "/api/health/ready") \
            and not path.startswith(("/api/public-media/", "/api/public/")) and request.method != "OPTIONS":
        ip = request.client.host if request.client else "?"
        if ratelimit.blocked(ip, _MAX_FAILS, _WINDOW):
            return JSONResponse({"detail": "Trop d'essais. Réessayez dans 10 minutes."}, status_code=429)
        given = request.headers.get("x-access-code", "")
        if not secrets.compare_digest(given.encode(), code.encode()) and not _token_ok(given):
            ratelimit.fail(ip, _WINDOW)
            return JSONResponse({"detail": "Code d'accès requis"}, status_code=401)
        ratelimit.reset(ip)
    return await call_next(request)


_OPEN_PATHS = ("/api/ping", "/api/linkedin/callback", "/api/instagram/callback",
               "/api/auth/status", "/api/health/live", "/api/health/ready")


def _protected(path: str, method: str) -> bool:
    return path.startswith("/api/") and method != "OPTIONS" and path not in _OPEN_PATHS \
        and not path.startswith(("/api/public-media/", "/api/public/"))


def _is_loopback(request: Request) -> bool:
    """Usage local (même machine) : reste possible sans code."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def _origins() -> list[str]:
    raw = (settings.allowed_origins or "").strip()
    if not raw:
        return ["*"] if settings.unic_env != "production" else []
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins() or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
    if settings.unic_env == "production":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


class _SelectiveGZip:
    """Compresse les réponses de plus de 1 Ko, sauf le flux de conversation (il doit partir mot par mot, sans mise en tampon)."""

    def __init__(self, app):
        self.plain = app
        self.zipped = GZipMiddleware(app, minimum_size=1000, compresslevel=5)

    async def __call__(self, scope, receive, send):
        stream = scope["type"] == "http" and scope["path"].startswith("/api/chat")
        await (self.plain if stream else self.zipped)(scope, receive, send)


app.add_middleware(_SelectiveGZip)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Erreur inattendue : journalisée côté serveur, réponse générique côté client (pas de trace exposée)."""
    logger.exception("Erreur non gérée sur %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Erreur interne du serveur."}, status_code=500)

app.include_router(router, prefix="/api")
app.include_router(reseaux_router, prefix="/api")
app.include_router(field_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(website_router, prefix="/api")


def startup():
    settings.data_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    ensure_indexes()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        try:
            from app import memory
            memory.seed_owner_rules(db)
            from app.seed import (apply_owner_hangers_v4, apply_owner_prices_v1, apply_owner_prices_v2, apply_owner_prices_v3,
                                  apply_owner_prices_v5)
            apply_owner_prices_v1(db)
            apply_owner_prices_v2(db)
            apply_owner_prices_v3(db)
            apply_owner_hangers_v4(db)
            apply_owner_prices_v5(db)
        except Exception:
            pass
        try:
            from app import backup
            backup.start_scheduler()   # sauvegarde chaque jour, gardée ici et dans la boîte mail
        except Exception:
            pass
        try:
            from app import selfcare
            selfcare.start()   # surveillance : incidents, agents endormis, contrôle quotidien, agents créés
        except Exception:
            pass
        try:
            from app import mail_account
            mail_account.load_into_runtime(db)   # compte Gmail connecté depuis l'appli
        except Exception:   # un secret illisible ne doit jamais empêcher le démarrage
            pass
    finally:
        db.close()


@app.get("/api/public/widget.js")
def site_widget():
    """Bulle de discussion pour le site (public, mise en cache 1 h)."""
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent / "static" / "site-widget.js", media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/public/chat")
async def site_chat(request: Request):
    """Chat public du site : réponses bornées, aucune donnée de l'entreprise exposée."""
    from app import sitechat
    from app.database import SessionLocal
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Requête invalide"}, status_code=400)
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    db = SessionLocal()
    try:
        out = sitechat.reply(db, body.get("session_id"), str(body.get("message") or ""), ip, str(body.get("page") or ""))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logger.exception("chat du site")
        return JSONResponse({"reply": sitechat.limit_reply(), "whatsapp": sitechat.whatsapp_number()}, status_code=200)
    finally:
        db.close()
    return out


@app.get("/api/health/live")
def health_live():
    """Liveness : le processus répond (aucune dépendance testée)."""
    return {"status": "alive"}


@app.get("/api/health/ready")
def health_ready():
    """Readiness : base de données (et Redis si configuré) joignables. 503 sinon."""
    from sqlalchemy import text
    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness : base de données injoignable")
        checks["database"] = "down"
    if settings.redis_url:
        client = ratelimit._client()
        try:
            checks["redis"] = "ok" if client is not None and client.ping() else "down"
        except Exception:
            checks["redis"] = "down"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)


@app.get("/api/ping")
def ping():
    return {"ok": True, "app": "UniC AI", "version": __version__}


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _index():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "app": "UniC AI",
        "message": "Interface non compilée. En développement, lancez le frontend Vite. "
        "En production : npm run build dans frontend/.",
    }


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def root():
        return _index()

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        candidate = FRONTEND_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return _index()
else:

    @app.get("/")
    def root_api_only():
        return _index()
