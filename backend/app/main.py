from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.api_reseaux import router as reseaux_router
from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_columns
from app.seed import seed_if_empty

app = FastAPI(
    title="UniC AI",
    description="Plateforme métier UniC Plaquiste — pas un assistant généraliste.",
    version=__version__,
)

_fails: dict[str, list[float]] = {}
_MAX_FAILS, _WINDOW = 10, 600.0


@app.middleware("http")
async def access_code_guard(request: Request, call_next):
    """Code d'accès unique sur /api/*. Ajouté AVANT le CORS : le 401 garde ses en-têtes CORS."""
    code = settings.unic_access_code
    path = request.url.path
    if code and path.startswith("/api/") and path != "/api/ping" and request.method != "OPTIONS":
        ip = request.client.host if request.client else "?"
        now = time.time()
        recent = [t for t in _fails.get(ip, []) if now - t < _WINDOW]
        if len(recent) >= _MAX_FAILS:
            return JSONResponse({"detail": "Trop d'essais. Réessayez dans 10 minutes."}, status_code=429)
        given = request.headers.get("x-access-code", "")
        if not secrets.compare_digest(given.encode(), code.encode()):
            _fails[ip] = recent + [now]
            return JSONResponse({"detail": "Code d'accès requis"}, status_code=401)
        _fails.pop(ip, None)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(reseaux_router, prefix="/api")


@app.on_event("startup")
def startup():
    settings.data_path.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        try:
            from app import mail_account
            mail_account.load_into_runtime(db)   # compte Gmail connecté depuis l'appli
        except Exception:   # un secret illisible ne doit jamais empêcher le démarrage
            pass
    finally:
        db.close()


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
