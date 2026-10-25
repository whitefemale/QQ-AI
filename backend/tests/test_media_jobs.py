from __future__ import annotations

import pytest
from app.adapters.media.local_store import LocalMediaStore
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.models.media import MediaTranscript
from app.providers.registry import build_default_registry
from sqlalchemy import func, select

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _services(settings: Settings, database: Database) -> tuple[MediaService, MediaJobService]:
    store = LocalMediaStore(settings.media_path, max_bytes=1024 * 1024)
    registry = build_default_registry()
    registry.set_enabled("mock.vision", True)
    router = CapabilityRouter(registry)
    media_service = MediaService(database, store, settings)
    return media_service, MediaJobService(database, router, media_service)


async def test_media_job_succeeds_and_is_idempotent(settings: Settings, database: Database) -> None:
    media_service, jobs = _services(settings, database)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image", account_id="acc")

    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="job-1",
    )
    duplicate = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="job-1",
    )
    assert duplicate.id == job.id

    processed = await jobs.process_job(job.id)
    assert processed.status == "succeeded"
    assert processed.output_ref

    async with database.session() as session:
        transcript = await session.get(MediaTranscript, processed.output_ref)
        assert transcript is not None
        assert transcript.is_mock is True
        assert "Mock" in transcript.text

    again = await jobs.process_job(job.id)
    assert again.status == "succeeded"
    async with database.session() as session:
        count = await session.scalar(select(func.count()).select_from(MediaTranscript))
    assert count == 1


async def test_media_job_cancel_and_no_provider(settings: Settings, database: Database) -> None:
    media_service, jobs = _services(settings, database)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")

    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="job-cancel",
    )
    cancelled = await jobs.cancel_job(job.id)
    assert cancelled.status == "cancelled"
    assert (await jobs.process_job(job.id)).status == "cancelled"

    registry = build_default_registry()  # 所有 Mock 默认关闭
    media_service2 = MediaService(database, LocalMediaStore(settings.media_path, max_bytes=1024 * 1024), settings)
    jobs2 = MediaJobService(database, CapabilityRouter(registry), media_service2)
    unavailable = await jobs2.create_job(
        capability="audio.transcribe",
        media_ref=asset.id,
        job_type="audio",
        idempotency_key="job-no-provider",
    )
    failed = await jobs2.process_job(unavailable.id)
    assert failed.status == "queued"  # max_attempts=2，第一次失败后等待重试
    assert failed.error_code == "PROVIDER_CAPABILITY_MISSING"
    failed_again = await jobs2.process_job(unavailable.id)
    assert failed_again.status == "failed"

    with pytest.raises(AppError) as excinfo:
        await jobs2.retry_job(unavailable.id)
    assert excinfo.value.code == "MEDIA_JOB_RETRY_EXHAUSTED"
