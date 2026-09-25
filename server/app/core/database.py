"""Асинхронный движок SQLAlchemy, фабрика сессий и базовый класс моделей."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей."""


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: одна сессия на запрос."""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Создаёт таблицы, если их нет."""
    from app.models import orm  # noqa: F401 — импорт регистрирует модели в Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
