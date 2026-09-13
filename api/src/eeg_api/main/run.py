"""Application factory.

``make_app()`` is the entry point; ``app`` at module scope exists so that
``uvicorn eeg_api.main.run:app`` works without a factory flag.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from eeg_api.config import Settings, get_settings
from eeg_api.main.api.routers import channels, flows, recordings, sessions, stream, system
from eeg_api.services.catalog import load_catalog
from eeg_api.services.hub import AcquisitionHub
from eeg_api.services.library import FlowStore, RecordingLibrary


logger = logging.getLogger("eeg_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the process-scoped singletons once, and release them on shutdown."""
    settings: Settings = getattr(app.state, "settings", None) or get_settings()

    # The catalog is static prose; it is read once, and it refuses to start if it
    # disagrees with the montage. A wrong channel doc is worse than a missing one.
    app.state.catalog = load_catalog(settings.catalog_file)

    # Flow definitions are the operator's own data, so they get their own folder
    # rather than living inside recordings/ (which is git-ignored and disposable).
    app.state.flows = FlowStore(settings.flows_dir)
    app.state.flows.ensure_seeds()

    app.state.library = RecordingLibrary(settings.recordings_dir, settings.fs)
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)

    hub = AcquisitionHub(settings, app.state.catalog)
    app.state.hub = hub
    await hub.start()
    logger.info(
        "eeg api ready: source=%s recordings=%s catalog=%d channels",
        hub.mode,
        settings.recordings_dir,
        len(app.state.catalog.channels),
    )

    try:
        yield
    finally:
        await hub.shutdown()


def make_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved = settings or get_settings()

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.version,
        description=(
            "Live EEG from an Emotiv EPOC+ dongle, decoded locally. Streams over "
            "WebSocket, documents every channel, and records labelled datasets from "
            "guided protocols."
        ),
        lifespan=lifespan,
    )
    # The lifespan reads this back, so an explicitly passed Settings is honoured.
    app.state.settings = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router, prefix="/api")
    app.include_router(channels.router, prefix="/api")
    app.include_router(recordings.router, prefix="/api")
    app.include_router(flows.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(stream.router)

    @app.get("/health", tags=["system"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": resolved.environment, "version": resolved.version}

    _mount_web(app, resolved.web_dist)
    return app


def _mount_web(app: FastAPI, web_dist: Path) -> None:
    """Serve the built Angular app, if it has been built.

    Registered last on purpose: the API routes above must win. A catch-all that
    answers with ``index.html`` is what makes a deep link like ``/flows/new`` work —
    Angular owns the path after the first load, and a plain static mount would 404 it.
    """
    index = web_dist / "index.html"

    if not index.exists():

        @app.get("/", include_in_schema=False)
        def not_built() -> dict[str, str]:
            return {
                "message": "The web UI is not built yet.",
                "build": "npm --prefix web install && npm --prefix web run build",
                "api_docs": "/docs",
            }

        return

    assets = web_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "ws")) or path == "health":
            raise HTTPException(status_code=404, detail="not found")
        candidate = (web_dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


app = make_app()
