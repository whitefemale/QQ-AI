"""模型列表：状态映射、Mock/未配置/不支持、只读且不写用量。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from app.adapters.llm.base import BaseLLMProvider
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.llm_gateway import LLMGateway
from app.schemas.llm import LLMModelInfo, ModelListResult
from sqlalchemy import func, select


@dataclass
class Env:
    gateway: LLMGateway
    database: Database
    provider_id: str


class ModelListAdapter(BaseLLMProvider):
    provider_type = "openai_compatible"

    def __init__(
        self,
        provider_id: str,
        result: ModelListResult | None = None,
        error: AppError | None = None,
    ) -> None:
        super().__init__(provider_id=provider_id, name="models", model="")
        self.result = result
        self.error = error
        self.calls = 0

    async def generate(self, request: Any) -> Any:  # pragma: no cover - 本文件不使用
        raise AssertionError("模型列表测试不应调用 generate")

    async def list_models(self, timeout_seconds: float | None = None) -> ModelListResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


async def _env(
    database: Database,
    settings: Settings,
    *,
    provider_type: str = "openai_compatible",
    enabled: bool = True,
    model: str | None = "demo-model",
) -> Env:
    async with database.session() as session:
        provider = LLMProvider(
            name="模型列表测试",
            provider_type=provider_type,
            base_url="https://llm.example.invalid/v1" if provider_type != "mock" else None,
            model=model if provider_type != "mock" else (model or "mock-model"),
            enabled=enabled,
        )
        session.add(provider)
        await session.commit()
        provider_id = provider.id
    gateway = LLMGateway(
        database,
        settings,
        CredentialCipher(settings.credential_encryption_key or ""),
        BudgetService(database, settings),
    )
    return Env(gateway=gateway, database=database, provider_id=provider_id)


def _install(monkeypatch: pytest.MonkeyPatch, env: Env, adapter: BaseLLMProvider) -> None:
    monkeypatch.setattr(env.gateway, "_adapter_for", lambda record, require_model=True: adapter)


async def _usage_count(database: Database) -> int:
    async with database.session() as session:
        return int(await session.scalar(select(func.count()).select_from(LLMUsage)) or 0)


@pytest.mark.asyncio
async def test_mock_provider_returns_mock_state_without_remote_call(
    database: Database,
    settings: Settings,
) -> None:
    env = await _env(database, settings, provider_type="mock")
    result = await env.gateway.list_models(env.provider_id)

    assert result.supported is False
    assert result.state == "mock"
    assert result.models == []
    assert "Mock" in (result.message or "")
    assert await _usage_count(database) == 0


@pytest.mark.asyncio
async def test_missing_config_maps_to_not_configured(
    database: Database,
    settings: Settings,
) -> None:
    env = await _env(database, settings)
    result = await env.gateway.list_models(env.provider_id)

    assert result.supported is False
    assert result.state == "not_configured"
    assert result.error_code == ErrorCode.LLM_NOT_CONFIGURED
    assert await _usage_count(database) == 0


@pytest.mark.asyncio
async def test_disabled_provider_can_still_list_models(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings, enabled=False)
    adapter = ModelListAdapter(
        env.provider_id,
        result=ModelListResult(
            supported=True,
            state="available",
            models=[LLMModelInfo(id="demo-model")],
        ),
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.list_models(env.provider_id)

    assert result.state == "available"
    assert result.current_model_listed is True
    assert adapter.calls == 1
    assert await _usage_count(database) == 0


@pytest.mark.asyncio
async def test_model_list_does_not_require_model_id(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings, model=None)
    adapter = ModelListAdapter(
        env.provider_id,
        result=ModelListResult(supported=True, state="available", models=[LLMModelInfo(id="discovered")]),
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.list_models(env.provider_id)

    assert result.state == "available"
    assert result.current_model_listed is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "expected_state"),
    [
        (ErrorCode.LLM_AUTH_FAILED, "auth_failed"),
        (ErrorCode.LLM_RATE_LIMITED, "rate_limited"),
        (ErrorCode.LLM_TIMEOUT, "timeout"),
        (ErrorCode.LLM_NETWORK_ERROR, "network_error"),
        (ErrorCode.LLM_INVALID_RESPONSE, "invalid_response"),
    ],
)
async def test_model_list_errors_are_mapped_to_states(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_state: str,
) -> None:
    env = await _env(database, settings)
    adapter = ModelListAdapter(
        env.provider_id,
        error=AppError(error_code, "模型列表失败", status_code=502),
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.list_models(env.provider_id)

    assert result.supported is False
    assert result.state == expected_state
    assert result.error_code == error_code
    assert "手动填写模型 ID" in (result.note or "")
    assert await _usage_count(database) == 0


@pytest.mark.asyncio
async def test_unsupported_result_is_passed_through(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ModelListAdapter(
        env.provider_id,
        result=ModelListResult(supported=False, state="unsupported", message="服务商未提供，请手动填写。"),
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.list_models(env.provider_id)

    assert result.supported is False
    assert result.state == "unsupported"
    assert "手动填写" in (result.message or "")


@pytest.mark.asyncio
async def test_missing_provider_is_not_found(database: Database, settings: Settings) -> None:
    gateway = LLMGateway(
        database,
        settings,
        CredentialCipher(settings.credential_encryption_key or ""),
        BudgetService(database, settings),
    )
    with pytest.raises(AppError) as caught:
        await gateway.list_models("missing-provider")
    assert caught.value.code == ErrorCode.PROVIDER_NOT_FOUND
