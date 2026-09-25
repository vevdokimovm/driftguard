"""Настройки сервера из переменных окружения и .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация сервера контроля дрейфа."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite+aiosqlite:///./driftguard.db"
    API_TOKEN: str = ""  # токен клиента; пусто — API открыт (локально)
    AGENT_TOKEN: str = ""  # общий токен агентов; пусто — снимки принимаются без него
    AUTO_BASELINE: bool = True  # первый снимок нового хоста сразу становится эталоном
    STALE_AFTER_SECONDS: int = 60  # хост без снимков дольше этого считается потерянным
    MAX_SNAPSHOT_ITEMS: int = 5000  # предел записей в одном разделе снимка


settings = Settings()
