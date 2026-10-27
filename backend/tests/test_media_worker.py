"""媒体后台 worker：不阻塞事件循环、失败隔离、可停止。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.adapters.media.local_store import LocalMediaStore
from app.core.config import Settings
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.media.worker import MediaWorker
from app.models.media import MediaJob
from app.providers.registry import build_default_registry

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _services(settings: Settings, database: Database) -> tuple[MediaService, MediaJobService]:
    store = LocalMediaStore(settings.media_path, max_bytes=1024 * 1024)
    registry = build_default_registry()
    registry.set_enabled("mock.vision", True)
    media_service = MediaService(database, store, settings)
    return media_service, MediaJobService(database, CapabilityRouter(registry), media_service)


async def _status(database: Database, job_id: str) -> str | None:
    async with database.session() as session:
        job = await session.get(MediaJob, job_id)
        return job.status if job is not None else None


async def test_worker_processes_queued_jobs_and_stops(settings: Settings, database: Database) -> None:
    media_service, jobs = _services(settings, database)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="worker-job",
    )
    assert await _status(database, job.id) == "queued"

    worker = MediaWorker(jobs, interval_seconds=0.5, batch_size=10)
    await worker.start()
    assert worker.running is True
    try:
        for _ in range(50):
            if await _status(database, job.id) == "succeeded":
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("媒体 worker 未在预期时间内处理任务")
    finally:
        await worker.stop()
    assert worker.running is False


async def test_worker_keeps_running_after_polling_error() -> None:
    class ExplodingJobs:
        def __init__(self) -> None:
            self.calls = 0

        async def process_due_jobs(self, limit: int = 10) -> int:  # noqa: ARG002
            self.calls += 1
            raise RuntimeError("transient failure")

    fake: Any = ExplodingJobs()
    worker = MediaWorker(fake, interval_seconds=0.5, batch_size=1)
    await worker.start()
    try:
        await asyncio.sleep(0.7)
        assert worker.running is True
        assert fake.calls >= 1
    finally:
        await worker.stop()
    assert worker.running is False


async def test_worker_stop_is_idempotent() -> None:
    class NoopJobs:
        async def process_due_jobs(self, limit: int = 10) -> int:  # noqa: ARG002
            return 0

    worker = MediaWorker(NoopJobs(), interval_seconds=0.5, batch_size=1)
    await worker.stop()  # 未启动时停止不应报错
    await worker.start()
    await worker.stop()
    await worker.stop()
    assert worker.running is False
