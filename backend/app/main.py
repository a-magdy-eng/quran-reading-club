"""Application factory."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from . import APP_NAME, __version__
from .api import router
from .backup import create_backup, latest_backup_age_hours
from .clock import Clock
from .config import AppConfig, Paths, default_data_dir, frontend_dist_dir, load_config
from .db import Database
from .deps import AppState
from .models import Group
from .quran import get_quran
from .security import NetworkAllowList
from .streaks import finalize_group
from .tracking import close_stale_sessions

log = logging.getLogger("readingclub")

MAINTENANCE_INTERVAL_SECONDS = 60


def run_maintenance(st: AppState) -> None:
    """Finalise finished days for every group and close dead sessions."""
    t = st.clock.now()
    with st.db.session() as db:
        for group in db.scalars(select(Group)):
            finalize_group(db, group, t)
        close_stale_sessions(db, t)


def maybe_auto_backup(st: AppState) -> Path | None:
    hours = st.config.auto_backup_hours
    if hours <= 0:
        return None
    age = latest_backup_age_hours(st.paths)
    if age is None or age >= hours:
        path = create_backup(st.paths, keep=st.config.backups_to_keep)
        log.info("Automatic backup written to %s", path)
        return path
    return None


def create_app(
    data_dir: Path | None = None,
    clock: Clock | None = None,
    config: AppConfig | None = None,
    serve_frontend: bool = True,
    background_tasks: bool = True,
    sharing_provider=None,
) -> FastAPI:
    paths = Paths(Path(data_dir) if data_dir else default_data_dir())
    paths.ensure()
    cfg = config or load_config(paths)
    db = Database(paths.db_path)
    db.init_schema()
    get_quran()  # load + validate the Quran text at startup
    st = AppState(
        db=db,
        config=cfg,
        paths=paths,
        clock=clock or Clock(),
        allowlist=NetworkAllowList(cfg.allowed_networks),
        sharing=sharing_provider,
    )
    run_maintenance(st)  # catch up on days that ended while the server was off

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if background_tasks:
            try:
                await run_in_threadpool(maybe_auto_backup, st)
            except Exception:  # never block startup on a backup problem
                log.exception("Automatic backup failed")

            async def loop():
                while True:
                    await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
                    try:
                        await run_in_threadpool(run_maintenance, st)
                        await run_in_threadpool(maybe_auto_backup, st)
                    except Exception:
                        log.exception("Maintenance failed")

            task = asyncio.create_task(loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
            db.dispose()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.rc = st
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def network_guard(request: Request, call_next):
        host = request.client.host if request.client else None
        if st.allowlist is not None and not st.allowlist.allows(host):
            log.warning("Refused request from non-private address %s", host)
            return PlainTextResponse("Access is limited to the private network.", status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest: str):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    dist = frontend_dist_dir()
    if serve_frontend:
        index = dist / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if not index.exists():
                return PlainTextResponse(
                    "The web interface has not been built. Run: cd frontend && npm run build", status_code=503
                )
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
