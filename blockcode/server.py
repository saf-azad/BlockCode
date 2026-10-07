"""FastAPI server: JSON API under /api and the built web app at /."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from blockcode import __version__

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def create_app(projects_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="BlockCode", version=__version__)
    app.state.projects_dir = Path(projects_dir or "projects").resolve()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
