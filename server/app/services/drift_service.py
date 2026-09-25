"""Бизнес-логика: приём снимков, эталоны, состояние хостов и события дрейфа."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import HostNotFoundError, NoSnapshotError
from app.models.orm import Host, Snapshot
from app.models.schemas import ChangeOut, EventOut, HostStatus, SnapshotAck, SnapshotIn, SnapshotOut
from app.repositories.drift_repository import DriftRepository
from app.services import drift as engine

logger = logging.getLogger(__name__)


class DriftService:
    """Операции, которые вызывают агенты и клиент."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = DriftRepository(session)

    async def ingest(self, data: SnapshotIn, agent_ip: str) -> SnapshotAck:
        """Принимает снимок от агента, сохраняет новый вариант конфигурации и отмечает смену состояния."""
        host = await self.repo.get_host_by_name(data.hostname)
        if host is None:
            host = await self.repo.add_host(Host(name=data.hostname))
            self.repo.log(agent_ip, "host_registered", host.name)
        host.last_seen_at = datetime.now(timezone.utc)
        host.agent_ip = agent_ip

        payload = engine.normalize(data.payload())
        fingerprint = engine.digest(payload)
        previous = await self.repo.latest_snapshot(host.id)
        stored = previous is None or previous.digest != fingerprint
        snapshot = previous
        if stored:
            snapshot = await self.repo.add_snapshot(Snapshot(host_id=host.id, digest=fingerprint, data=payload))

        baseline = await self.repo.get_baseline(host.id)
        if baseline is None and settings.AUTO_BASELINE:
            await self.repo.set_baseline(host.id, snapshot.id, "auto")
            self.repo.add_event(host.id, "baseline_accepted", 0, "первый снимок принят как эталон")
            await self.repo.commit()
            return SnapshotAck(host_id=host.id, state="OK", changes=0, stored=stored)
        if baseline is None:
            await self.repo.commit()
            return SnapshotAck(host_id=host.id, state="NO_BASELINE", changes=0, stored=stored)

        reference = (await self.repo.get_snapshot(baseline.snapshot_id)).data
        changes = engine.compare(reference, payload)
        if stored and previous is not None:
            was_drifting = bool(engine.compare(reference, previous.data))
            if changes:
                self.repo.add_event(host.id, "drift_detected", len(changes), engine.summary(changes))
                logger.warning("drift on %s: %s", host.name, engine.summary(changes))
            elif was_drifting:
                self.repo.add_event(host.id, "drift_resolved", 0, "конфигурация вернулась к эталону")
        await self.repo.commit()
        return SnapshotAck(host_id=host.id, state="DRIFT" if changes else "OK", changes=len(changes), stored=stored)

    async def status(self) -> list[HostStatus]:
        """Для таблицы в клиенте: состояние каждого хоста и число расхождений."""
        out = []
        now = datetime.now(timezone.utc)
        for host in await self.repo.list_hosts():
            baseline = await self.repo.get_baseline(host.id)
            changes = await self._changes(host.id)
            if host.last_seen_at is None or now - _aware(host.last_seen_at) > timedelta(
                    seconds=settings.STALE_AFTER_SECONDS):
                state = "STALE"
            elif baseline is None:
                state = "NO_BASELINE"
            else:
                state = "DRIFT" if changes else "OK"
            out.append(HostStatus(
                id=host.id, name=host.name, state=state, changes=len(changes), last_seen_at=host.last_seen_at,
                baseline_accepted_at=baseline.accepted_at if baseline else None,
                baseline_accepted_by=baseline.accepted_by if baseline else None, agent_ip=host.agent_ip))
        return out

    async def drift(self, host_id: int) -> list[ChangeOut]:
        """Расхождения последнего снимка хоста с его эталоном."""
        await self._get(host_id)
        return [ChangeOut(**c.as_dict()) for c in await self._changes(host_id)]

    async def accept_baseline(self, host_id: int, client_ip: str) -> HostStatus:
        """Делает последний снимок хоста новым эталоном: изменения признаны правильными."""
        host = await self._get(host_id)
        latest = await self.repo.latest_snapshot(host_id)
        if latest is None:
            raise NoSnapshotError(host_id)
        was = len(await self._changes(host_id))
        await self.repo.set_baseline(host_id, latest.id, client_ip)
        self.repo.add_event(host_id, "baseline_accepted", was, f"принято расхождений: {was}")
        self.repo.log(client_ip, "baseline_accepted", f"{host.name} snapshot={latest.id} changes={was}")
        await self.repo.commit()
        return next(s for s in await self.status() if s.id == host_id)

    async def delete_host(self, host_id: int, client_ip: str) -> None:
        """Удаляет хост вместе со снимками и событиями."""
        host = await self._get(host_id)
        name = host.name
        self.repo.log(client_ip, "host_deleted", name)
        await self.repo.delete_host(host)

    async def snapshots(self, host_id: int, limit: int) -> list[SnapshotOut]:
        await self._get(host_id)
        return [SnapshotOut.model_validate(s) for s in await self.repo.snapshots(host_id, limit)]

    async def events(self, limit: int, host_id: int | None) -> list[EventOut]:
        if host_id is not None:
            await self._get(host_id)
        return [EventOut.model_validate(e) for e in await self.repo.events(limit, host_id)]

    async def _changes(self, host_id: int) -> list[engine.Change]:
        baseline = await self.repo.get_baseline(host_id)
        latest = await self.repo.latest_snapshot(host_id)
        if baseline is None or latest is None or baseline.snapshot_id == latest.id:
            return []
        reference = await self.repo.get_snapshot(baseline.snapshot_id)
        return engine.compare(reference.data, latest.data)

    async def _get(self, host_id: int) -> Host:
        host = await self.repo.get_host(host_id)
        if host is None:
            raise HostNotFoundError(host_id)
        return host


def _aware(moment: datetime) -> datetime:
    """SQLite отдаёт время без часового пояса, считаем его UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
