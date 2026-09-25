"""Приложение FastAPI: маршруты и перевод исключений в HTTP-ответы."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import agent_router, health_router, router
from app.core.database import init_db
from app.core.exceptions import HostNotFoundError, NoSnapshotError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DriftGuard", version="1.0.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(router)

    @app.exception_handler(HostNotFoundError)
    async def not_found(_: Request, exc: HostNotFoundError):
        return JSONResponse(status_code=404, content={"detail": f"host {exc} not found"})

    @app.exception_handler(NoSnapshotError)
    async def no_snapshot(_: Request, exc: NoSnapshotError):
        return JSONResponse(status_code=409, content={"detail": f"host {exc} has no snapshots yet"})

    return app


app = create_app()
