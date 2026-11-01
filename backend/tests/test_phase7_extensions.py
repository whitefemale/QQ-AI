"""阶段 7：扩展契约、能力真实性与停用即时止损。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.adapters.media.base import BaseMediaProvider, VisionProvider
from app.adapters.media.local_store import LocalMediaStore
from app.adapters.qq.base import AdapterCapabilities, BaseQQAdapter
from app.adapters.qq.factory import (
    QQAdapterFactory,
    QQAdapterRequest,
    QQAdapterSpec,
    build_default_qq_adapter_factory,
)
from app.adapters.qq.mock import MockQQAdapter
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.core.time import utcnow
from app.db.session import Database
from app.main import create_app
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.models.governance import AuditLog
from app.models.media import MediaTranscript
from app.plugins.registry import PluginService
from app.plugins.runtime import get_plugin_runtime, runtime_requirements
from app.providers.registry import CAPABILITY_TYPES, ProviderRegistry, build_default_registry
from app.schemas.llm import ConnectionTestResult
from app.schemas.media import ImageUnderstandRequest, MediaUnderstandingResult
from app.services.provider_service import ProviderService
from fastapi.testclient import TestClient
from sqlalchemy import func, select

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _data(response: Any, expected_status: int = 200) -> Any:
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["error"] is None, body
    return body["data"]


@pytest.fixture
def client(settings: Settings) -> Any:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _media_stack(
    settings: Settings,
    database: Database,
    *,
    registry: Any | None = None,
) -> tuple[MediaService, MediaJobService, ProviderService, Any]:
    registry = registry or build_default_registry()
    store = LocalMediaStore(settings.media_path, max_bytes=1024 * 1024)
    media_service = MediaService(database, store, settings)
    jobs = MediaJobService(database, CapabilityRouter(registry), media_service)
    providers = ProviderService(
        database,
        CredentialCipher(settings.credential_encryption_key),
        None,  # type: ignore[arg-type] 本测试不触达 LLM 网关
        registry,
        media_jobs=jobs,
    )
    return media_service, jobs, providers, registry


async def test_disabling_media_provider_cancels_queued_jobs(settings: Settings, database: Database) -> None:
    media_service, jobs, providers, _registry = _media_stack(settings, database)
    await providers.set_media_provider_enabled("mock.vision", True)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")

    first = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="phase7-queued-1",
    )
    second = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="phase7-queued-2",
    )

    result = await providers.set_media_provider_enabled("mock.vision", False)
    assert result["enabled"] is False
    assert result["cancelled_jobs"] == 2
    assert set(result["cancelled_capabilities"]) == {"image.describe", "image.understand"}

    for job_id in (first.id, second.id):
        processed = await jobs.process_job(job_id)
        assert processed.status == "cancelled"
        assert processed.error_code == ErrorCode.PROVIDER_CAPABILITY_MISSING

    async with database.session() as session:
        transcript_count = await session.scalar(select(func.count()).select_from(MediaTranscript))
    assert transcript_count == 0

    async with database.session() as session:
        audit = await session.scalar(
            select(AuditLog)
            .where(AuditLog.action == "provider.media.toggle")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    assert audit is not None
    assert audit.details_json["cancelled_jobs"] == 2
    assert audit.details_json["enabled"] is False


class _SlowVisionProvider(VisionProvider):
    provider_id = "test.slow_vision"
    name = "慢速测试视觉 Provider"
    version = "1.0.0"
    is_mock = False

    def __init__(self) -> None:
        super().__init__(provider_id=self.provider_id, name=self.name)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def capabilities(self) -> list[str]:
        return ["image.describe"]

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="测试实现")

    async def describe_image(self, request: ImageUnderstandRequest) -> MediaUnderstandingResult:
        self.started.set()
        await self.release.wait()
        return MediaUnderstandingResult(
            summary="迟到的模拟结果",
            provider_id=self.provider_id,
            confidence=0.5,
            is_mock=False,
        )


async def test_disabling_provider_discards_inflight_result(settings: Settings, database: Database) -> None:
    registry = build_default_registry()
    slow = _SlowVisionProvider()
    registry.register_provider(slow, enabled=False)
    media_service, jobs, providers, _registry = _media_stack(settings, database, registry=registry)
    await providers.set_media_provider_enabled("test.slow_vision", True)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")
    job = await jobs.create_job(
        capability="image.describe",
        media_ref=asset.id,
        job_type="image",
        idempotency_key="phase7-inflight",
    )

    task = asyncio.create_task(jobs.process_job(job.id))
    await asyncio.wait_for(slow.started.wait(), timeout=5)
    result = await providers.set_media_provider_enabled("test.slow_vision", False)
    assert result["cancelled_jobs"] == 1
    slow.release.set()
    processed = await asyncio.wait_for(task, timeout=5)

    assert processed.status == "cancelled"
    async with database.session() as session:
        transcript_count = await session.scalar(select(func.count()).select_from(MediaTranscript))
    assert transcript_count == 0


async def test_unconfigured_and_contract_only_capabilities_never_call_pseudo_impl(
    settings: Settings,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = build_default_registry()
    calls = {"tts": 0}

    async def _fake_synthesize(*args: Any, **kwargs: Any) -> Any:
        calls["tts"] += 1
        raise AssertionError("未实现的任务类型不得调用 Provider")

    mock_tts = registry.get("mock.tts")
    assert mock_tts is not None and mock_tts.provider is not None
    monkeypatch.setattr(mock_tts.provider, "synthesize", _fake_synthesize)

    media_service, jobs, providers, _registry = _media_stack(settings, database, registry=registry)
    asset = await media_service.ingest(PNG, mime="image/png", media_type="image")

    assert (
        await jobs.enqueue_segment(
            media_ref=asset.id,
            media_type="image",
            account_id=None,
            group_id=None,
            source_message_id="msg-unconfigured",
        )
        is None
    )

    await providers.set_media_provider_enabled("mock.tts", True)
    tts_job = await jobs.create_job(
        capability="audio.synthesize",
        media_ref=asset.id,
        job_type="tts",
        idempotency_key="phase7-tts-contract-only",
    )
    processed = await jobs.process_job(tts_job.id)
    assert processed.status == "queued"  # 第一次失败后仍按既有最大尝试次数等待
    assert processed.error_code == ErrorCode.PROVIDER_CAPABILITY_MISSING
    assert calls["tts"] == 0

    capabilities = {item["capability"]: item for item in await providers.capability_overview()}
    assert capabilities["audio.synthesize"]["execution"] == "contract_only"
    assert "任务队列不会执行" in capabilities["audio.synthesize"]["note"]
    assert capabilities["audio.synthesize"]["state"] == "mock_only"


def test_media_provider_contracts_cover_registry_and_state() -> None:
    registry = build_default_registry()
    for entry in registry.list_entries():
        assert entry.provider_type in set(CAPABILITY_TYPES.values()) | {
            "vision",
            "ocr",
            "asr",
            "tts",
            "embedding",
            "media_processor",
            "reranker",
            "video",
        }
        if entry.planned:
            assert entry.provider is None
            continue
        assert isinstance(entry.provider, BaseMediaProvider)
        assert entry.is_mock is bool(entry.provider.is_mock)
        assert entry.capabilities
        assert set(entry.capabilities).issubset(CAPABILITY_TYPES)
        assert all(CAPABILITY_TYPES[item] == entry.provider_type for item in entry.capabilities)
        assert entry.enabled is False  # 默认关闭，未显式启用前不能声称可用

    # 仅有规划占位时，路由必须报告 planned。
    planned_only = ProviderRegistry()
    planned_only.register_planned("planned.video", "video", "真实视频理解 Provider（未配置）", ["video.describe"])
    router = CapabilityRouter(planned_only)
    with pytest.raises(AppError) as excinfo:
        router.select("video.describe")
    assert excinfo.value.details["planned"] is True

    # 默认注册表里有已停用的 Mock 实现；这是未配置，不能谎报为 planned。
    router = CapabilityRouter(registry)
    with pytest.raises(AppError) as excinfo2:
        router.select("image.describe")
    assert excinfo2.value.details["planned"] is False
    assert excinfo2.value.details["state"] == "unconfigured"


def test_adapter_factory_registers_without_pipeline_changes() -> None:
    factory = build_default_qq_adapter_factory()
    modes = {item["value"]: item for item in factory.modes()}
    assert set(modes) == {"mock", "onebot11", "official"}
    assert modes["official"]["available"] is False
    assert modes["official"]["state"] == "planned"

    mock = factory.build("mock", QQAdapterRequest(instance_id="i", account_id="a"))
    assert isinstance(mock, BaseQQAdapter)
    assert isinstance(mock, MockQQAdapter)
    assert mock.capabilities().send_image is False

    with pytest.raises(AppError) as planned:
        factory.build("official", QQAdapterRequest(instance_id="i", account_id="a"))
    assert planned.value.code == ErrorCode.OPERATION_PLANNED
    assert planned.value.status_code == 501

    class _CustomAdapter(BaseQQAdapter):
        adapter_type = "custom"

        def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(receive_group_message=True, send_text=True)

        async def connect(self) -> None:
            await self._set_status("online")

        async def disconnect(self) -> None:
            await self._set_status("disconnected")

        async def send_text(self, conversation_id: str, text: str, **kwargs: Any) -> Any:
            self.touch_sent()
            return type("Sent", (), {"message_id": "m1"})()

    custom = QQAdapterFactory()
    custom.register(
        QQAdapterSpec(
            mode="custom",
            label="自定义",
            builder=lambda request: _CustomAdapter(
                instance_id=request.instance_id,
                account_id=request.account_id,
            ),
        )
    )
    adapter = custom.build("custom", QQAdapterRequest(instance_id="i2", account_id="a2"))
    assert adapter.adapter_type == "custom"
    assert adapter.capabilities().receive_group_message is True


async def test_plugin_runtime_is_manifest_only_with_complete_future_requirements(
    settings: Settings, database: Database
) -> None:
    requirements = {item["key"]: item for item in runtime_requirements()}
    assert set(requirements) == {
        "sandbox",
        "permission_manifest",
        "user_confirmation",
        "signature_verification",
        "timeout",
        "resource_limits",
        "audit",
        "disable",
    }
    assert all(item["note"] for item in requirements.values())

    runtime = get_plugin_runtime()
    with pytest.raises(AppError) as excinfo:
        await runtime.execute(type("Request", (), {"plugin_id": "x", "capability": "y"})())  # type: ignore[arg-type]
    assert excinfo.value.code == ErrorCode.OPERATION_PLANNED

    directory = settings.plugins_path / "demo.runtime"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        '{"id":"demo.runtime","name":"运行时示例","permissions":["messages:read"]}',
        encoding="utf-8",
    )
    service = PluginService(database, settings)
    await service.sync()
    data = await service.get("demo.runtime")
    assert data["execution"] == "not_executed"
    assert data["runtime_status"] == "runtime_planned"
    assert {item["key"] for item in data["runtime_requirements"]} == set(requirements)
    with pytest.raises(AppError) as planned:
        await service.set_enabled("demo.runtime", True)
    assert planned.value.code == ErrorCode.OPERATION_PLANNED
    assert (await service.get("demo.runtime"))["enabled"] is False


def test_extension_capability_matrix_api_is_honest(client: TestClient) -> None:
    data = _data(client.get("/api/extensions/capabilities"))
    contracts = {item["kind"]: item for item in data["contracts"]}
    assert set(contracts) == {"chat_adapter", "llm_provider", "media_provider", "tool", "plugin"}
    assert contracts["chat_adapter"]["interface"] == "BaseQQAdapter"
    assert contracts["plugin"]["execution"] == "not_executed"
    assert any("不执行" in item or "不加载" in item for item in contracts["plugin"]["guarantees"])

    tool_names = {item["name"] for item in data["tools"]}
    assert tool_names == {"calculator", "current_datetime"}
    assert all(item["execution"] == "in_process" for item in data["tools"])
    assert all(item["registration"] == "fixed_at_startup" for item in data["tools"])

    media = {item["capability"]: item for item in data["media"]}
    for item in media.values():
        assert item["state"] in {"mock_only", "available", "unconfigured", "planned"}
        assert item["source"] == "provider_registry"
        assert item["checked_at"]
        assert item["execution"] in {"job", "contract_only"}
        assert item["next_step"]
    assert media["image.describe"]["execution"] == "job"
    assert media["video.describe"]["execution"] == "contract_only"

    builtin = next(item for item in data["plugins"] if item["id"] == "builtin.core-tools")
    assert builtin["execution"] == "builtin_in_process"
    assert builtin["runtime_requirements"] == []
    assert any("立即取消" in note for note in data["notes"])


def test_media_capabilities_expose_state_and_next_step(client: TestClient) -> None:
    items = _data(client.get("/api/media/capabilities"))["items"]
    image = next(item for item in items if item["capability"] == "image.describe")
    assert image["execution"] == "job"
    assert image["source"] == "provider_registry"
    assert image["checked_at"]
    assert "Mock" in image["next_step"] or "真实" in image["next_step"]
    assert isinstance(image["last_error"], (str, type(None)))


async def test_cancel_running_job_marks_terminal(settings: Settings, database: Database) -> None:
    _media_service, jobs, _providers, registry = _media_stack(settings, database)
    registry.set_enabled("mock.vision", True)
    job = await jobs.create_job(
        capability="image.describe",
        media_ref="0" * 64,
        job_type="image",
        idempotency_key="phase7-manual-cancel-running",
    )
    async with database.session() as session:
        row = await session.get(type(job), job.id)
        assert row is not None
        row.status = "running"
        row.started_at = utcnow()
        await session.commit()
    cancelled = await jobs.cancel_job(job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.finished_at is not None
    assert (await jobs.process_job(job.id)).status == "cancelled"
