from __future__ import annotations

import pytest
from app.adapters.media.local_store import LocalMediaStore
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.media.usage import MediaUsageService
from app.models.account import Account
from app.models.governance import UsageEvent
from app.models.media import MediaProviderUsage, MediaTranscript
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


def _services_full(
    settings: Settings, database: Database, budgets: BudgetService | None = None
) -> tuple[MediaService, MediaJobService, MediaUsageService]:
    store = LocalMediaStore(settings.media_path, max_bytes=1024 * 1024)
    registry = build_default_registry()
    registry.set_enabled("mock.vision", True)
    media_service = MediaService(database, store, settings)
    usage = MediaUsageService(database)
    jobs = MediaJobService(
        database,
        CapabilityRouter(registry),
        media_service,
        budgets=budgets,
        usage=usage,
    )
    return media_service, jobs, usage


async def test_success_persists_provider_and_records_usage(settings: Settings, database: Database) -> None:
    budgets = BudgetService(database, settings)
    media_service, jobs, _usage = _services_full(settings, database, budgets)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        input_data={"account_id": "acc-x", "group_id": "group-x", "mime": "image/png"},
        idempotency_key="persist-provider",
    )
    processed = await jobs.process_job(job.id)
    assert processed.status == "succeeded"
    assert processed.provider_id == "mock.vision"

    async with database.session() as session:
        stored = await session.get(type(job), job.id)
        assert stored is not None
        assert stored.provider_id == "mock.vision"
        usage_rows = list((await session.execute(select(MediaProviderUsage))).scalars())
        budget_rows = list(
            (await session.execute(select(UsageEvent).where(UsageEvent.feature == "media.image.describe"))).scalars()
        )
    assert len(usage_rows) == 1
    assert usage_rows[0].provider_id == "mock.vision"
    assert usage_rows[0].is_mock is True
    assert usage_rows[0].external_cost == 0.0
    assert usage_rows[0].succeeded is True
    # 媒体用量同时进入预算计量：global/account/group/feature 各一条 requests。
    assert budget_rows
    assert {row.scope_type for row in budget_rows} >= {"global", "account", "group", "feature"}
    assert all(row.metric == "requests" for row in budget_rows)


async def test_budget_exhaustion_is_terminal_and_never_retries_loop(settings: Settings, database: Database) -> None:
    budgets = BudgetService(database, settings)
    await budgets.upsert_policy(
        {
            "scope_type": "feature",
            "scope_id": "media.image.describe",
            "window": "day",
            "metric": "requests",
            "limit_value": 1,
        }
    )
    await budgets.record(
        provider_id=None,
        group_id=None,
        feature="media.image.describe",
        requests=1,
    )

    media_service, jobs, _usage = _services_full(settings, database, budgets)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="budget-blocked",
    )
    blocked = await jobs.process_job(job.id)
    assert blocked.status == "failed"
    assert blocked.error_code == "BUDGET_EXCEEDED"
    assert blocked.attempts == 1

    async with database.session() as session:
        usage_count = await session.scalar(select(func.count()).select_from(MediaProviderUsage))
    # 预算在 Provider 调用前阻断，不应产生任何 Provider 用量。
    assert usage_count == 0

    # 手动重试仍受预算约束：第二次到达上限后终态失败。
    await jobs.retry_job(job.id)
    still_blocked = await jobs.process_job(job.id)
    assert still_blocked.status == "failed"
    assert still_blocked.error_code == "BUDGET_EXCEEDED"
    with pytest.raises(AppError) as excinfo:
        await jobs.retry_job(job.id)
    assert excinfo.value.code == "MEDIA_JOB_RETRY_EXHAUSTED"


async def test_account_budget_is_applied_to_media_jobs(settings: Settings, database: Database) -> None:
    async with database.session() as session:
        session.add_all(
            [
                Account(id="acc-media", display_name="媒体账号", adapter_type="mock"),
                Account(id="acc-other", display_name="其他账号", adapter_type="mock"),
            ]
        )
        await session.commit()

    budgets = BudgetService(database, settings)
    await budgets.upsert_policy(
        {
            "scope_type": "account",
            "scope_id": "acc-media",
            "window": "day",
            "metric": "requests",
            "limit_value": 1,
        }
    )
    await budgets.record(provider_id=None, group_id=None, account_id="acc-media", feature="media.image.describe")

    media_service, jobs, _usage = _services_full(settings, database, budgets)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    blocked = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        input_data={"account_id": "acc-media", "group_id": None, "mime": "image/png"},
        idempotency_key="account-budget-blocked",
    )
    assert (await jobs.process_job(blocked.id)).status == "failed"

    allowed = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        input_data={"account_id": "acc-other", "group_id": None, "mime": "image/png"},
        idempotency_key="account-budget-allowed",
    )
    assert (await jobs.process_job(allowed.id)).status == "succeeded"
