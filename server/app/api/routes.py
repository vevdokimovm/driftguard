"""HTTP-слой: разобрать запрос, вызвать сервис, вернуть схему."""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.schemas import AuditOut, ChangeOut, EventOut, HostStatus, SnapshotAck, SnapshotIn, SnapshotOut
from app.repositories.drift_repository import DriftRepository
from app.services.drift_service import DriftService


def _check(expected: str, given: str, header: str) -> None:
    """Если токен задан, сравнивает за постоянное время; пустой токен — проверка выключена."""
    if expected and not secrets.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail=f"invalid or missing {header}")


def require_token(x_api_token: str = Header(default="")) -> None:
    _check(settings.API_TOKEN, x_api_token, "X-API-Token")


def require_agent_token(x_agent_token: str = Header(default="")) -> None:
    _check(settings.AGENT_TOKEN, x_agent_token, "X-Agent-Token")


router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
agent_router = APIRouter(prefix="/api", dependencies=[Depends(require_agent_token)])
health_router = APIRouter(prefix="/api")


def service(session: AsyncSession = Depends(get_session)) -> DriftService:
    return DriftService(session)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@health_router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@agent_router.post("/snapshots", response_model=SnapshotAck)
async def ingest(data: SnapshotIn, request: Request, svc: DriftService = Depends(service)):
    return await svc.ingest(data, client_ip(request))


@router.get("/hosts", response_model=list[HostStatus])
async def hosts(svc: DriftService = Depends(service)):
    return await svc.status()


@router.get("/hosts/{host_id}/drift", response_model=list[ChangeOut])
async def host_drift(host_id: int, svc: DriftService = Depends(service)):
    return await svc.drift(host_id)


@router.post("/hosts/{host_id}/baseline", response_model=HostStatus)
async def accept_baseline(host_id: int, request: Request, svc: DriftService = Depends(service)):
    return await svc.accept_baseline(host_id, client_ip(request))


@router.delete("/hosts/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host(host_id: int, request: Request, svc: DriftService = Depends(service)):
    await svc.delete_host(host_id, client_ip(request))


@router.get("/hosts/{host_id}/snapshots", response_model=list[SnapshotOut])
async def host_snapshots(host_id: int, limit: int = Query(20, ge=1, le=200), svc: DriftService = Depends(service)):
    return await svc.snapshots(host_id, limit)


@router.get("/events", response_model=list[EventOut])
async def events(limit: int = Query(50, ge=1, le=200), host_id: int | None = None,
                 svc: DriftService = Depends(service)):
    return await svc.events(limit, host_id)


@router.get("/audit", response_model=list[AuditOut])
async def audit(limit: int = Query(50, ge=1, le=200), session: AsyncSession = Depends(get_session)):
    return await DriftRepository(session).audit(limit)
