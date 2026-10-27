"""媒体用量：Mock 零成本、未知成本不伪造、聚合维度与旁路失败隔离。"""

from __future__ import annotations

from typing import Any

from app.adapters.media.local_store import LocalMediaStore
from app.core.config import Settings
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.media.usage import MediaUsageService
from app.models.media import MediaProviderUsage
from app.providers.registry import build_default_registry
from sqlalchemy import select

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_mock_calls_record_zero_external_cost(database: Database) -> None:
    usage = MediaUsageService(database)
    await usage.record(
        provider_id="mock.vision",
        capability="image.describe",
        job_type="image",
        is_mock=True,
        external_cost=9.99,  # Mock 不允许记成真实费用
        latency_ms=12.5,
    )
    data = await usage.aggregate(hours=24)
    assert data["calls"] == 1
    assert data["mock_calls"] == 1
    assert data["external_cost"] == 0.0
    assert data["cost_status"] == "complete"
    assert "不" in data["note"] and "转写" in data["note"]


async def test_real_unknown_cost_is_not_reported_as_zero(database: Database) -> None:
    usage = MediaUsageService(database)
    await usage.record(
        provider_id="real.vision",
        capability="image.describe",
        job_type="image",
        is_mock=False,
        external_cost=None,
    )
    data = await usage.aggregate(hours=24)
    assert data["external_cost"] is None
    assert data["cost_status"] == "unknown"
    assert data["by_provider"][0]["cost_status"] == "unknown"


async def test_partial_cost_reports_unknown_total(database: Database) -> None:
    usage = MediaUsageService(database)
    await usage.record(
        provider_id="mock.ocr",
        capability="ocr.extract",
        job_type="image",
        is_mock=True,
    )
    await usage.record(
        provider_id="real.ocr",
        capability="ocr.extract",
        job_type="image",
        is_mock=False,
        external_cost=None,
    )
    data = await usage.aggregate(hours=24)
    assert data["cost_status"] == "partial"
    assert data["external_cost"] is None


async def test_aggregate_by_provider_capability_and_filters(database: Database) -> None:
    usage = MediaUsageService(database)
    await usage.record(
        provider_id="mock.vision",
        capability="image.describe",
        job_type="image",
        account_id="acc-1",
        group_id="group-1",
        is_mock=True,
        succeeded=True,
        latency_ms=10,
    )
    await usage.record(
        provider_id="mock.vision",
        capability="image.describe",
        job_type="image",
        account_id="acc-1",
        group_id="group-1",
        is_mock=True,
        succeeded=False,
        error_code="PROVIDER_TIMEOUT",
        latency_ms=30,
    )
    await usage.record(
        provider_id="mock.ocr",
        capability="ocr.extract",
        job_type="image",
        account_id="acc-2",
        group_id="group-2",
        is_mock=True,
        latency_ms=20,
    )

    data = await usage.aggregate(hours=24)
    assert data["calls"] == 3
    assert data["successful_calls"] == 2
    assert data["failed_calls"] == 1
    assert data["latency_ms_avg"] == 20.0

    providers = {item["provider_id"]: item for item in data["by_provider"]}
    assert providers["mock.vision"]["calls"] == 2
    assert providers["mock.vision"]["failed_calls"] == 1
    assert providers["mock.ocr"]["calls"] == 1

    capabilities = {item["capability"]: item for item in data["by_capability"]}
    assert capabilities["image.describe"]["calls"] == 2
    assert capabilities["ocr.extract"]["calls"] == 1

    filtered = await usage.aggregate(hours=24, account_id="acc-2")
    assert filtered["calls"] == 1
    assert filtered["by_capability"][0]["capability"] == "ocr.extract"

    group_filtered = await usage.aggregate(hours=24, group_id="group-2", capability="image.describe")
    assert group_filtered["calls"] == 0
    assert group_filtered["cost_status"] == "no_calls"
    assert group_filtered["external_cost"] is None


def _job_services(settings: Settings, database: Database, *, usage: Any) -> tuple[MediaService, MediaJobService]:
    store = LocalMediaStore(settings.media_path, max_bytes=1024 * 1024)
    registry = build_default_registry()
    registry.set_enabled("mock.vision", True)
    media_service = MediaService(database, store, settings)
    jobs = MediaJobService(
        database,
        CapabilityRouter(registry),
        media_service,
        usage=usage,
    )
    return media_service, jobs


async def test_usage_write_failure_does_not_fail_successful_job(database: Database, settings: Settings) -> None:
    class ExplodingUsage:
        async def record(self, **kwargs: Any) -> None:
            raise RuntimeError("usage store down")

    media_service, jobs = _job_services(settings, database, usage=ExplodingUsage())
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="usage-failure-job",
    )
    processed = await jobs.process_job(job.id)
    assert processed.status == "succeeded"
    assert processed.output_ref


async def test_failed_attempt_is_recorded_without_content(database: Database, settings: Settings) -> None:
    registry = build_default_registry()  # 全部 Mock 默认关闭
    media_service = MediaService(database, LocalMediaStore(settings.media_path, max_bytes=1024), settings)
    usage = MediaUsageService(database)
    jobs = MediaJobService(database, CapabilityRouter(registry), media_service, usage=usage)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="ocr.extract",
        media_ref=asset.id,
        job_type="image",
        input_data={"mime": "image/png", "secret_text": "不应入库"},
        idempotency_key="failed-usage-job",
    )
    failed = await jobs.process_job(job.id)
    assert failed.status == "queued"
    assert failed.error_code == "PROVIDER_CAPABILITY_MISSING"

    async with database.session() as session:
        rows = list((await session.execute(select(MediaProviderUsage))).scalars())
    assert len(rows) == 1
    row = rows[0]
    assert row.succeeded is False
    assert row.error_code == "PROVIDER_CAPABILITY_MISSING"
    assert row.provider_id is None
    assert row.capability == "ocr.extract"
    assert not hasattr(row, "text")
