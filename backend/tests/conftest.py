from __future__ import annotations

from collections.abc import AsyncIterator

import app.models  # noqa: F401  确保所有表注册到 Base.metadata
import pytest
import pytest_asyncio
from app import __version__
from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from cryptography.fernet import Fernet


@pytest.fixture
def settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=str(data_dir),
        database_url=f"sqlite+aiosqlite:///{(data_dir / 'test.db').as_posix()}",
        credential_encryption_key=Fernet.generate_key().decode("utf-8"),
        app_secret_key="test-secret",
        app_version=__version__,
        # 测试不依赖本机是否已构建前端，SPA 回退行为由测试自行断言。
        frontend_dist=str(tmp_path / "no-frontend-dist"),
        # 测试绝不扫描仓库本机真实 connectors/，避免读取真实安装或进程状态。
        connectors_dir=str(tmp_path / "connectors"),
    )
    settings.ensure_directories()
    return settings


@pytest_asyncio.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()
