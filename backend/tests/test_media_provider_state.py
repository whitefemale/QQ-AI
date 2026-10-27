"""媒体 Provider 启停/健康状态持久化：重启保留、未知记录忽略、写失败回滚。"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.governance import AuditLog
from app.models.provider import ProviderRegistry as MediaProviderState
from app.providers.registry import build_default_registry
from app.services.provider_service import ProviderService
from sqlalchemy import select


def _service(database: Database, settings: Settings) -> ProviderService:
    return ProviderService(
        database,
        CredentialCipher(settings.credential_encryption_key),
        None,  # type: ignore[arg-type] 这些测试不触达 LLM 网关
        build_default_registry(),
    )


async def _stored(database: Database, provider_id: str) -> MediaProviderState | None:
    async with database.session() as session:
        return await session.get(MediaProviderState, provider_id)


async def test_enable_state_survives_registry_rebuild(database: Database, settings: Settings) -> None:
    service = _service(database, settings)
    assert service.registry.get("mock.vision") is not None
    assert service.registry.get("mock.vision").enabled is False

    public = await service.set_media_provider_enabled("mock.vision", True)
    assert public["enabled"] is True
    assert public["health_status"] == "healthy"

    stored = await _stored(database, "mock.vision")
    assert stored is not None
    assert stored.enabled is True
    assert stored.health_status == "healthy"

    # 模拟重启：全新的注册表从数据库恢复。
    rebooted = _service(database, settings)
    assert rebooted.registry.get("mock.vision").enabled is False
    await rebooted.load_media_provider_state()
    entry = rebooted.registry.get("mock.vision")
    assert entry is not None
    assert entry.enabled is True
    assert entry.health_status == "healthy"
    assert entry.status == "available"
    assert rebooted.registry.available_for("image.describe")

    async with database.session() as session:
        audits = list(
            (await session.execute(select(AuditLog).where(AuditLog.action == "provider.media.toggle"))).scalars()
        )
    assert len(audits) == 1


async def test_disable_state_survives_reload(database: Database, settings: Settings) -> None:
    service = _service(database, settings)
    await service.set_media_provider_enabled("mock.ocr", True)
    await service.set_media_provider_enabled("mock.ocr", False)

    rebooted = _service(database, settings)
    await rebooted.load_media_provider_state()
    entry = rebooted.registry.get("mock.ocr")
    assert entry is not None
    assert entry.enabled is False
    assert entry.status == "disabled"
    assert rebooted.registry.available_for("ocr.extract") == []


async def test_unknown_persisted_provider_is_ignored(database: Database, settings: Settings) -> None:
    async with database.session() as session:
        session.add(
            MediaProviderState(
                id="legacy.vision",
                provider_type="vision",
                name="历史 Provider",
                capabilities_json=["image.describe"],
                config_schema_json={},
                enabled=True,
                status="available",
                health_status="healthy",
                is_mock=False,
            )
        )
        await session.commit()

    service = _service(database, settings)
    before = len(service.registry.list_entries())
    await service.load_media_provider_state()
    assert service.registry.get("legacy.vision") is None
    assert len(service.registry.list_entries()) == before


async def test_persist_failure_does_not_change_memory_state(
    database: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(database, settings)

    async def _fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_persist_media_provider", _fail)
    with pytest.raises(AppError) as excinfo:
        await service.set_media_provider_enabled("mock.vision", True)
    assert excinfo.value.code == "INTERNAL_ERROR"
    assert service.registry.get("mock.vision").enabled is False
    assert await _stored(database, "mock.vision") is None


async def test_health_persist_failure_rolls_back_snapshot(
    database: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(database, settings)
    await service.set_media_provider_enabled("mock.vision", True)
    entry = service.registry.require("mock.vision")
    entry.health_status = "stale"

    async def _fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_persist_media_provider", _fail)
    with pytest.raises(AppError) as excinfo:
        await service.test_media_provider("mock.vision")
    assert excinfo.value.code == "INTERNAL_ERROR"
    assert entry.health_status == "stale"


async def test_planned_provider_cannot_be_enabled(database: Database, settings: Settings) -> None:
    service = _service(database, settings)
    with pytest.raises(AppError):
        await service.set_media_provider_enabled("planned.reranker", True)
    with pytest.raises(AppError):
        service.registry.require("does.not.exist")
