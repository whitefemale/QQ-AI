"""异步数据库引擎与会话管理。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


def _configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args={"timeout": 30} if settings.database_url.startswith("sqlite") else {},
        )
        if settings.database_url.startswith("sqlite"):
            _configure_sqlite(self.engine)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()
