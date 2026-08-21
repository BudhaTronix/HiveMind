"""FastAPI application factory with injectable state for deterministic tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hivemind.config import Settings, load_settings
from hivemind.persistence import ArtifactStore, HiveMindRepository
from hivemind.web.api import router
from hivemind.web.broker import LiveBroker
from hivemind.web.run_supervisor import RunSupervisor


def create_app(
    *,
    settings: Settings | None = None,
    repository: HiveMindRepository | None = None,
    broker: LiveBroker | None = None,
    supervisor: RunSupervisor | None = None,
) -> FastAPI:
    """Build an isolated single-process browser API."""

    active_settings = settings or load_settings()
    active_settings.ensure_directories()
    active_repository = repository or HiveMindRepository(active_settings.db_path)
    active_broker = broker or LiveBroker()
    artifacts = ArtifactStore(active_settings.runs_dir)
    active_supervisor = supervisor or RunSupervisor(
        active_settings, active_repository, artifacts, active_broker
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await active_repository.initialize()
        yield
        await active_supervisor.shutdown()

    app = FastAPI(
        title="HiveMind Web API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.repository = active_repository
    app.state.broker = active_broker
    app.state.supervisor = active_supervisor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    root = Path(__file__).resolve().parents[3]
    dist = root / "web" / "dist"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if dist.is_dir() and (dist / "index.html").is_file():
            requested = dist / path
            if path and requested.is_file() and dist in requested.resolve().parents:
                return FileResponse(requested)
            return FileResponse(dist / "index.html")
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Browser assets are not built. Run `cd web && npm install && npm run build`, "
                    "or use the Vite development server on http://127.0.0.1:5173."
                )
            },
        )
