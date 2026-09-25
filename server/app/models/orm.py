"""Таблицы БД: хосты, снимки конфигурации, эталоны, события дрейфа и журнал действий."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Host(Base):
    """Машина, на которой работает агент."""

    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_ip: Mapped[str] = mapped_column(String(64), default="")


class Snapshot(Base):
    """Снимок конфигурации. Одинаковые подряд не сохраняются, у хоста растёт только last_seen_at."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    digest: Mapped[str] = mapped_column(String(64))  # sha256 канонического JSON снимка
    data: Mapped[dict] = mapped_column(JSON)


class Baseline(Base):
    """Эталон хоста: ссылка на снимок, который принят как правильное состояние."""

    __tablename__ = "baselines"

    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_by: Mapped[str] = mapped_column(String(64))


class DriftEvent(Base):
    """Смена состояния хоста: дрейф найден, дрейф ушёл, принят эталон."""

    __tablename__ = "drift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(30))
    changes: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[str] = mapped_column(String(500), default="")


class AuditLog(Base):
    """Журнал работы сервера: кто, что и когда сделал."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    client_ip: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[str] = mapped_column(String(500), default="")
