"""保留策略：级联清理、引用保护、日志边界与诚实状态。"""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest
from app.adapters.media.local_store import LocalMediaStore
from app.core.config import Settings
from app.core.errors import AppError
from app.core.time import utcnow
from app.db.session import Database
from app.main import create_app
from app.media.service import MediaService
from app.models.account import Account
from app.models.governance import AuditLog
from app.models.group import Group
from app.models.media import MediaAsset
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message
from app.models.persona import Persona, PersonaEvolutionEvent, PersonaTrait, PersonaVersion
from app.services.memory_service import MemoryService
from app.services.persona_store import PersonaStore
from app.services.retention import RetentionScheduler, RetentionService, normalize_retention_days
from app.services.settings_store import get_global_pause, get_setting, set_global_pause, set_setting
from fastapi.testclient import TestClient
from sqlalchemy import select

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _services(settings: Settings, database: Database) -> tuple[RetentionService, MediaService]:
    media = MediaService(database, LocalMediaStore(settings.media_path, max_bytes=1024 * 1024), settings)
    service = RetentionService(database, settings, media, PersonaStore(database), MemoryService(database, settings))
    return service, media


async def _seed_account(database: Database) -> None:
    async with database.session() as session:
        session.add(Account(id="acc", display_name="测试账号"))
        await session.commit()


def _message(
    message_id: str,
    *,
    days_old: float,
    segments: list[dict] | None = None,
    content: str = "旧消息",
) -> Message:
    return Message(
        id=message_id,
        platform_message_id=f"p-{message_id}",
        account_id="acc",
        conversation_id="group-1",
        conversation_type="group",
        sender_id="user-1",
        direction="inbound",
        content_text=content,
        segments_json=segments or [],
        event_timestamp=utcnow() - timedelta(days=days_old),
        processing_status="processed",
    )


async def _add(database: Database, *records: object) -> None:
    async with database.session() as session:
        session.add_all(records)
        await session.commit()


async def test_old_messages_are_deleted_once_and_new_messages_are_kept(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    await _add(database, _message("old-1", days_old=120), _message("new-1", days_old=1))
    service, _media = _services(settings, database)

    first = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert first["status"] == "completed"
    assert first["counts"]["messages"] == 1
    assert first["counts"]["batches"] == 1
    assert first["error"] is None

    async with database.session() as session:
        remaining = list((await session.execute(select(Message.id))).scalars())
    assert remaining == ["new-1"]

    second = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert second["counts"]["messages"] == 0
    assert second["counts"]["batches"] == 0


async def test_persona_evidence_and_memory_sources_are_scrubbed_before_delete(
    settings: Settings, database: Database
) -> None:
    await _seed_account(database)
    await _add(
        database,
        _message("m1", days_old=120),
        _message("m2", days_old=119),
        _message("kept", days_old=1),
        Group(id="group-1", account_id="acc", platform_group_id="platform-group-1"),
        Persona(id="persona-1", name="空白人格", mode="emergent"),
        PersonaTrait(
            id="trait-1",
            persona_id="persona-1",
            trait_key="tone",
            trait_value="简洁",
            evidence_message_ids_json=["m1", "m2", "kept"],
            evidence_count=3,
            status="stable",
        ),
        PersonaEvolutionEvent(
            id="event-1",
            persona_id="persona-1",
            batch_id="batch-1",
            trigger_message_id="m1",
            proposal_json={"proposed_traits": [{"evidence_message_ids": ["m1"]}]},
            old_state_json={"evidence_message_ids": ["m1", "m2"]},
            new_state_json={"traits": [{"evidence_message_ids": ["m1"]}]},
            result="pending_review",
        ),
        PersonaVersion(
            id="version-1",
            persona_id="persona-1",
            version_no=1,
            snapshot_json={"traits": [{"evidence_message_ids": ["m1", "m2"]}]},
        ),
        Memory(
            id="memory-1",
            account_id="acc",
            group_id=None,
            memory_type="fact",
            content="测试记忆",
            source_message_ids_json=["m1", "kept"],
            confidence=0.8,
            sensitivity="normal",
        ),
        MemoryCandidate(
            id="candidate-pending",
            account_id="acc",
            group_id="group-1",
            memory_type="fact",
            content="待审核",
            source_message_ids_json=["m1"],
            status="pending",
        ),
        MemoryCandidate(
            id="candidate-approved",
            account_id="acc",
            group_id="group-1",
            memory_type="fact",
            content="已审核",
            source_message_ids_json=["m1"],
            status="approved",
        ),
    )
    service, _media = _services(settings, database)
    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")

    assert summary["status"] == "completed"
    assert summary["counts"]["persona_traits_updated"] == 1
    assert summary["counts"]["persona_traits_demoted"] == 1
    assert summary["counts"]["persona_events_updated"] == 1
    assert summary["counts"]["persona_proposals_rejected"] == 1
    assert summary["counts"]["persona_versions_updated"] == 1
    assert summary["counts"]["memories_scrubbed"] == 1
    assert summary["counts"]["memory_candidates_updated"] == 1
    assert summary["counts"]["memory_candidates_deleted"] == 1

    async with database.session() as session:
        trait = await session.get(PersonaTrait, "trait-1")
        event = await session.get(PersonaEvolutionEvent, "event-1")
        version = await session.get(PersonaVersion, "version-1")
        memory = await session.get(Memory, "memory-1")
        pending = await session.get(MemoryCandidate, "candidate-pending")
        approved = await session.get(MemoryCandidate, "candidate-approved")
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "persona.evidence.batch_delete"))
        scrub_audit = await session.scalar(select(AuditLog).where(AuditLog.action == "memory.sources.scrub"))

    assert trait is not None
    assert trait.evidence_message_ids_json == ["kept"]
    assert trait.evidence_count == 1
    assert trait.status == "candidate"
    assert event is not None
    assert event.trigger_message_id is None
    assert event.result == "rejected"
    assert "自动拒绝" in (event.error_message or "")
    assert "m1" not in json.dumps(event.new_state_json)
    assert version is not None
    assert "m1" not in json.dumps(version.snapshot_json)
    assert memory is not None
    assert memory.source_message_ids_json == ["kept"]
    assert memory.content == "测试记忆"
    assert pending is None
    assert approved is not None
    assert approved.source_message_ids_json == []
    assert audit is not None
    assert scrub_audit is not None


async def test_media_from_deleted_messages_is_removed_but_shared_media_is_protected(
    settings: Settings, database: Database
) -> None:
    await _seed_account(database)
    service, media = _services(settings, database)
    old_media = await media.ingest(PNG, mime="image/png", media_type="image", account_id="acc")
    new_bytes = PNG + b"shared"
    shared = await media.ingest(new_bytes, mime="image/png", media_type="image", account_id="acc")
    await _add(
        database,
        _message("old-media", days_old=120, segments=[{"type": "image", "media_ref": old_media.id}]),
        _message("old-shared", days_old=120, segments=[{"type": "image", "media_ref": shared.id}]),
        _message("new-shared", days_old=1, segments=[{"type": "image", "media_ref": shared.id}]),
    )

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["counts"]["media_from_messages"] == 1
    assert await media.store.exists(old_media.id) is False
    assert await media.store.exists(shared.id) is True
    async with database.session() as session:
        old_asset = await session.get(MediaAsset, old_media.id)
        shared_asset = await session.get(MediaAsset, shared.id)
    assert old_asset is not None and old_asset.deleted_at is not None
    assert shared_asset is not None and shared_asset.deleted_at is None


async def test_expired_media_is_cleaned_but_still_referenced_media_is_kept(
    settings: Settings, database: Database
) -> None:
    await _seed_account(database)
    service, media = _services(settings, database)
    expired = await media.ingest(PNG, mime="image/png", media_type="image")
    referenced = await media.ingest(PNG + b"kept", mime="image/png", media_type="image")
    await _add(
        database,
        _message("kept-message", days_old=1, segments=[{"type": "image", "media_ref": referenced.id}]),
    )
    async with database.session() as session:
        for asset_id in (expired.id, referenced.id):
            asset = await session.get(MediaAsset, asset_id)
            assert asset is not None
            asset.expires_at = utcnow() - timedelta(days=1)
        await session.commit()

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["counts"]["media_expired"] == 1
    assert await media.store.exists(expired.id) is False
    assert await media.store.exists(referenced.id) is True


async def test_only_rotated_old_logs_are_deleted(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    await set_setting(database, "retention", {"log_retention_days": 2})
    logs = settings.logs_path
    current = logs / "app.log"
    rotated_old = logs / "app.log.1"
    rotated_new = logs / "app.log.2"
    unrelated = logs / "other.txt"
    for path in (current, rotated_old, rotated_new, unrelated):
        path.write_text("log", encoding="utf-8")
    old_time = (utcnow() - timedelta(days=5)).timestamp()
    new_time = utcnow().timestamp()
    os.utime(rotated_old, (old_time, old_time))
    os.utime(unrelated, (old_time, old_time))
    os.utime(rotated_new, (new_time, new_time))
    os.utime(current, (old_time, old_time))
    service, _media = _services(settings, database)

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["counts"]["logs"] == 1
    assert current.exists()
    assert rotated_new.exists()
    assert unrelated.exists()
    assert not rotated_old.exists()


async def test_global_pause_does_not_block_local_cleanup(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    await _add(database, _message("old-1", days_old=120))
    await set_global_pause(database, paused=True, reason="测试", actor="tester")
    service, _media = _services(settings, database)

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["global_pause"] is True
    assert summary["counts"]["messages"] == 1
    pause = await get_global_pause(database)
    assert pause["paused"] is True


async def test_batch_limit_reports_truncated(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    await _add(
        database,
        _message("old-1", days_old=130),
        _message("old-2", days_old=125),
        _message("old-3", days_old=120),
    )
    limited = settings.model_copy(update={"retention_batch_size": 1, "retention_max_batches_per_run": 1})
    service, _media = _services(limited, database)

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["counts"]["messages"] == 1
    assert summary["truncated"] is True
    async with database.session() as session:
        assert len(list((await session.execute(select(Message.id))).scalars())) == 2


async def test_auto_cleanup_is_off_by_default_and_persists_toggle(settings: Settings, database: Database) -> None:
    service, _media = _services(settings, database)
    status = await service.status()
    assert status["auto"]["enabled"] is False
    assert status["auto"]["source"] == "config"
    assert status["last_run"] is None
    assert status["scheduler"] is None

    await service.set_enabled(True, actor="tester")
    status = await service.status()
    assert status["auto"]["enabled"] is True
    assert status["auto"]["source"] == "setting"
    stored = await get_setting(database, "retention_auto")
    assert stored["enabled"] is True

    with pytest.raises(AppError) as excinfo:
        await service.set_enabled("yes")  # type: ignore[arg-type]
    assert excinfo.value.code == "VALIDATION_ERROR"


async def test_concurrent_run_is_rejected_and_scheduler_skips_overlap(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    service, _media = _services(settings, database)
    scheduler = RetentionScheduler(service, interval_seconds=60)
    assert isinstance(scheduler, RetentionScheduler)
    await service.set_enabled(True, actor="tester")

    async with service._lock:  # noqa: SLF001 - 直接模拟正在运行
        with pytest.raises(AppError) as excinfo:
            await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
        assert excinfo.value.code == "CONFLICT"
        assert excinfo.value.status_code == 409
        await scheduler._tick()  # noqa: SLF001 - 调度器应吞掉冲突而不是崩溃


async def test_retention_status_reports_last_run(settings: Settings, database: Database) -> None:
    await _seed_account(database)
    await _add(database, _message("old-1", days_old=120))
    service, _media = _services(settings, database)

    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    status = await service.status()
    assert status["last_run"] is not None
    assert status["last_run"]["status"] == "completed"
    assert status["last_run"]["trigger"] == "manual"
    assert status["last_run"]["counts"]["messages"] == 1
    assert status["last_run"]["finished_at"] == summary["finished_at"]


def test_retention_days_normalization() -> None:
    assert normalize_retention_days(None) == {
        "log_retention_days": 30,
        "message_retention_days": 90,
        "media_retention_days": 30,
        "memory_retention_days": 0,
    }
    assert normalize_retention_days({"message_retention_days": 0})["message_retention_days"] == 90
    assert normalize_retention_days({"message_retention_days": "7"})["message_retention_days"] == 7
    # 记忆保留的 0 是“关闭自动清理”，必须保持为 0，不能被改写成默认天数。
    assert normalize_retention_days({"memory_retention_days": 0})["memory_retention_days"] == 0
    assert normalize_retention_days({"memory_retention_days": "30"})["memory_retention_days"] == 30
    assert normalize_retention_days({"memory_retention_days": -1})["memory_retention_days"] == 0


def test_manual_retention_endpoint_requires_confirmation_and_audits(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        status = client.get("/api/system/retention/status")
        assert status.status_code == 200, status.text
        data = status.json()["data"]
        assert data["auto"]["enabled"] is False
        assert data["running"] is False

        enabled = client.put("/api/settings", json={"retention_auto": {"enabled": True}})
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["data"]["retention_status"]["auto"]["enabled"] is True

        # 预览只读：不写审计、不更新 last_run，也不删除任何数据。
        preview = client.get("/api/system/retention/preview")
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()["data"]
        assert preview_data["counts"]["messages_expired"] == 0
        assert preview_data["counts"]["messages_will_delete"] == 0
        assert preview_data["running"] is False
        assert preview_data["truncated"] is False
        assert preview_data["limits"]["max_messages_per_run"] > 0
        assert client.get("/api/settings").json()["data"]["retention_status"]["last_run"] is None
        assert client.get("/api/audit?action=retention.run").json()["data"]["total"] == 0

        missing_confirm = client.post("/api/system/retention/run")
        assert missing_confirm.status_code == 400, missing_confirm.text
        assert missing_confirm.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        assert client.get("/api/settings").json()["data"]["retention_status"]["last_run"] is None
        assert client.get("/api/audit?action=retention.run").json()["data"]["total"] == 0

        run = client.post("/api/system/retention/run", json={"confirm": "CLEANUP"})
        assert run.status_code == 200, run.text
        summary = run.json()["data"]
        assert summary["status"] == "completed"
        assert summary["trigger"] == "manual"
        assert summary["counts"]["messages"] == 0

        settings_body = client.get("/api/settings").json()["data"]
        assert settings_body["retention_status"]["last_run"]["status"] == "completed"

        audit = client.get("/api/audit?action=retention.run")
        assert audit.status_code == 200, audit.text
        items = audit.json()["data"]["items"]
        assert items and items[0]["action"] == "retention.run"

        invalid = client.put("/api/settings", json={"retention_auto": {"enabled": "yes"}})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_memory_retention_zero_disables_and_positive_days_deletes_unpinned(
    settings: Settings, database: Database
) -> None:
    await _seed_account(database)
    old_time = utcnow() - timedelta(days=40)
    await _add(
        database,
        Memory(
            id="memory-old",
            account_id="acc",
            group_id=None,
            memory_type="fact",
            content="旧记忆",
            source_message_ids_json=[],
            confidence=0.7,
            sensitivity="normal",
            created_at=old_time,
        ),
        Memory(
            id="memory-old-pinned",
            account_id="acc",
            group_id=None,
            memory_type="fact",
            content="固定旧记忆",
            source_message_ids_json=[],
            confidence=0.7,
            sensitivity="normal",
            is_pinned=True,
            created_at=old_time,
        ),
        Memory(
            id="memory-new",
            account_id="acc",
            group_id=None,
            memory_type="fact",
            content="新记忆",
            source_message_ids_json=[],
            confidence=0.7,
            sensitivity="normal",
        ),
    )
    service, _media = _services(settings, database)

    # 默认 0 = 不自动清理，即使记忆很旧。
    await set_setting(database, "retention", {"memory_retention_days": 0})
    disabled = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert disabled["counts"]["memories_deleted"] == 0
    async with database.session() as session:
        assert await session.get(Memory, "memory-old") is not None

    await set_setting(database, "retention", {"memory_retention_days": 7})
    enabled = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert enabled["counts"]["memories_deleted"] == 1
    async with database.session() as session:
        assert await session.get(Memory, "memory-old") is None
        assert await session.get(Memory, "memory-old-pinned") is not None
        assert await session.get(Memory, "memory-new") is not None


async def test_missing_logs_directory_is_tolerated(settings: Settings, database: Database) -> None:
    root = settings.logs_path
    for item in root.iterdir():
        item.unlink()
    root.rmdir()
    service, _media = _services(settings, database)
    summary = await service.run(trigger="manual", actor="tester", confirm="CLEANUP")
    assert summary["status"] == "completed"
    assert summary["counts"]["logs"] == 0
