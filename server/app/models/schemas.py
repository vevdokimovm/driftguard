"""Схемы Pydantic: отдельные модели для входа и выхода."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class FileState(BaseModel):
    """Состояние одного отслеживаемого файла."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: str = Field(pattern=r"^0[0-7]{3,4}$")
    owner: str = Field(min_length=1, max_length=100)


class SnapshotIn(BaseModel):
    """Снимок, который присылает агент."""

    hostname: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    files: dict[str, FileState] = {}
    packages: dict[str, str] = {}
    ports: list[str] = []

    @field_validator("files", "packages", "ports")
    @classmethod
    def bounded(cls, value):
        if len(value) > settings.MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"too many items (max {settings.MAX_SNAPSHOT_ITEMS})")
        return value

    @field_validator("ports")
    @classmethod
    def port_format(cls, value: list[str]) -> list[str]:
        for port in value:
            proto, _, number = port.partition("/")
            if proto not in ("tcp", "udp") or not number.isdigit() or not 0 < int(number) < 65536:
                raise ValueError(f"bad port '{port}', expected like tcp/22")
        return value

    def payload(self) -> dict:
        """Разделы снимка в виде обычного словаря для расчёта дрейфа и хранения."""
        return {"files": {k: v.model_dump() for k, v in self.files.items()},
                "packages": self.packages, "ports": self.ports}


class SnapshotAck(BaseModel):
    """Ответ агенту: что сервер понял из снимка."""

    host_id: int
    state: str
    changes: int
    stored: bool  # False — снимок совпал с предыдущим и отдельно не сохранялся


class HostStatus(BaseModel):
    """Сводка по хосту для таблицы в клиенте."""

    id: int
    name: str
    state: str  # OK | DRIFT | NO_BASELINE | STALE
    changes: int
    last_seen_at: datetime | None
    baseline_accepted_at: datetime | None
    baseline_accepted_by: str | None
    agent_ip: str


class ChangeOut(BaseModel):
    """Одно расхождение с эталоном."""

    section: str
    key: str
    kind: str
    expected: str | None
    actual: str | None


class SnapshotOut(BaseModel):
    """Снимок в истории хоста."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    digest: str


class EventOut(BaseModel):
    """Событие дрейфа."""

    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    host_id: int
    kind: str
    changes: int
    details: str


class AuditOut(BaseModel):
    """Запись журнала действий."""

    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    client_ip: str
    action: str
    details: str
