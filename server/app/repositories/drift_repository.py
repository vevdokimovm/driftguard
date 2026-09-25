"""Доступ к данным: хосты, снимки, эталоны, события и журнал. Бизнес-логики здесь нет."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import AuditLog, Baseline, DriftEvent, Host, Snapshot


class DriftRepository:
    """Запросы к таблицам DriftGuard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def list_hosts(self) -> list[Host]:
        result = await self.session.execute(select(Host).order_by(Host.name))
        return list(result.scalars())

    async def get_host(self, host_id: int) -> Host | None:
        return await self.session.get(Host, host_id)

    async def get_host_by_name(self, name: str) -> Host | None:
        result = await self.session.execute(select(Host).where(Host.name == name))
        return result.scalar_one_or_none()

    async def add_host(self, host: Host) -> Host:
        self.session.add(host)
        await self.session.flush()
        return host

    async def delete_host(self, host: Host) -> None:
        # SQLite без PRAGMA foreign_keys каскад не выполняет, поэтому зависимые строки удаляются явно
        for model in (Baseline, DriftEvent, Snapshot):
            for row in (await self.session.execute(select(model).where(model.host_id == host.id))).scalars():
                await self.session.delete(row)
        await self.session.flush()
        await self.session.delete(host)
        await self.session.commit()

    async def latest_snapshot(self, host_id: int) -> Snapshot | None:
        result = await self.session.execute(
            select(Snapshot).where(Snapshot.host_id == host_id).order_by(Snapshot.id.desc()).limit(1))
        return result.scalar_one_or_none()

    async def get_snapshot(self, snapshot_id: int) -> Snapshot | None:
        return await self.session.get(Snapshot, snapshot_id)

    async def add_snapshot(self, snapshot: Snapshot) -> Snapshot:
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def snapshots(self, host_id: int, limit: int) -> list[Snapshot]:
        result = await self.session.execute(
            select(Snapshot).where(Snapshot.host_id == host_id).order_by(Snapshot.id.desc()).limit(limit))
        return list(result.scalars())

    async def get_baseline(self, host_id: int) -> Baseline | None:
        return await self.session.get(Baseline, host_id)

    async def set_baseline(self, host_id: int, snapshot_id: int, accepted_by: str) -> Baseline:
        baseline = await self.get_baseline(host_id)
        if baseline is None:
            baseline = Baseline(host_id=host_id, snapshot_id=snapshot_id, accepted_by=accepted_by)
            self.session.add(baseline)
        else:
            baseline.snapshot_id = snapshot_id
            baseline.accepted_by = accepted_by
            baseline.accepted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return baseline

    def add_event(self, host_id: int, kind: str, changes: int = 0, details: str = "") -> None:
        self.session.add(DriftEvent(host_id=host_id, kind=kind, changes=changes, details=details[:500]))

    async def events(self, limit: int, host_id: int | None = None) -> list[DriftEvent]:
        query = select(DriftEvent).order_by(DriftEvent.id.desc()).limit(limit)
        if host_id is not None:
            query = query.where(DriftEvent.host_id == host_id)
        return list((await self.session.execute(query)).scalars())

    def log(self, client_ip: str, action: str, details: str = "") -> None:
        """Добавляет запись в журнал; фиксируется вместе с основной операцией одним commit."""
        self.session.add(AuditLog(client_ip=client_ip, action=action, details=details[:500]))

    async def audit(self, limit: int) -> list[AuditLog]:
        result = await self.session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
        return list(result.scalars())
