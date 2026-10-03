from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.api_reseaux import router as reseaux_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.seed import seed_if_empty

app = FastAPI(
    title="UniC AI",
    description="Plateforme métier UniC Plaquiste — pas un assistant généraliste.",
    version=__version__,
)

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
    db = SessionLocal()
    try:
        seed_if_empty(db)
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
