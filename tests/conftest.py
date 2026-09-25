"""Фикстуры: чистая база SQLite на каждый тест и клиент API."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "agent"))


@pytest.fixture()
async def app_env(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    # переменные окружения важнее .env: локальный .env стенда не должен включать токены в тестах
    os.environ.update(API_TOKEN="", AGENT_TOKEN="", AUTO_BASELINE="true", STALE_AFTER_SECONDS="60")
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    from app.core import database
    from app.main import create_app

    await database.init_db()
    yield create_app(), database
    await database.engine.dispose()


@pytest.fixture()
async def client(app_env):
    import httpx

    app, _ = app_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_snapshot(hostname: str = "node-a", **overrides) -> dict:
    """Снимок как от агента: два файла, два пакета, один порт."""
    snapshot = {
        "hostname": hostname,
        "files": {
            "/srv/app/app.conf": {"sha256": "a" * 64, "mode": "0644", "owner": "root:root"},
            "/srv/app/run.sh": {"sha256": "b" * 64, "mode": "0755", "owner": "root:root"},
        },
        "packages": {"openssl": "3.0.15", "demo-tool": "1.0"},
        "ports": ["tcp/8080"],
    }
    snapshot.update(overrides)
    return snapshot
