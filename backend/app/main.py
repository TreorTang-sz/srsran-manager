"""FastAPI application factory.

Dev/mock mode: single process — web + watchdog + monitor together.
Production (split systemd):
  * srsran-manager.service  -> this app with SRSRAN_MANAGER_ONLY=1
  * srsran-watchdog.service -> python -m app.watchdog_runner
The web layer only consumes the Runtime; the watchdog never imports
FastAPI (principle: watchdog must not depend on the web manager).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import AppConfig, load_config
from app.runtime import Runtime, build_runtime

logger = logging.getLogger("srsran.main")


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    runtime = build_runtime(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        yield
        runtime.stop()

    app = FastAPI(
        title="srsRAN Manager",
        description="Management / monitoring / watchdog system for an srsRAN 4G base station",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.config = config

    from app.api import dev, enb, epc, events, network, radio, status, system, ws

    app.include_router(status.router)
    app.include_router(system.router)
    app.include_router(enb.router)
    app.include_router(epc.router)
    app.include_router(network.router)
    app.include_router(radio.router)
    app.include_router(events.router)
    app.include_router(ws.router)
    if runtime.faults is not None or config.security.dev_fault_api:
        app.include_router(dev.router)

    # serve the built Vue frontend (frontend/dist) when present
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(str(dist / "index.html"))

    return app


app = create_app()
