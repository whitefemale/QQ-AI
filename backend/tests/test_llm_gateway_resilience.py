"""网关安全重试、限流、取消与请求 ID 记录（不访问真实模型）。"""

from __future__ import annotations

import asyncio
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
from app.pipeline.provider_limiter import ProviderLimiter
from app.schemas.llm import LLMRequest, LLMResponse
from sqlalchemy import select


class ScriptedAdapter(BaseLLMProvider):
    provider_type = "openai_compatible"

    def __init__(self, provider_id: str, script: list[Any]) -> None:
        super().__init__(provider_id=provider_id, name="scripted", model="scripted-model")
        self.script = script
        self.calls = 0
        self.started = asyncio.Event()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.started.set()
        index = min(self.calls - 1, len(self.script) - 1)
        item = self.script[index]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, float):
            await asyncio.sleep(item)
            return LLMResponse(text="延迟后的回复", input_tokens=1, output_tokens=1)
        return item


@dataclass
class Env:
    gateway: LLMGateway
    database: Database
    provider_id: str


def _error(
    code: str,
    message: str,
    *,
    retryable: bool,
    safety: str,
    retry_after: float | None = None,
) -> AppError:
    details: dict[str, Any] = {"retry_safety": safety}
    if retry_after is not None:
        details["retry_after_seconds"] = retry_after
    return AppError(code, message, status_code=502, details=details, retryable=retryable)


def _settings(settings: Settings, **updates: Any) -> Settings:
    base = {
        "llm_retry_base_seconds": 0.0,
        "llm_retry_max_seconds": 0.0,
        "llm_retry_jitter_seconds": 0.0,
        "llm_retry_after_max_seconds": 30.0,
    }
    base.update(updates)
    return settings.model_copy(update=base)


async def _env(database: Database, settings: Settings, **updates: Any) -> Env:
    async with database.session() as session:
        provider = LLMProvider(
            name="重试测试模型",
            provider_type="openai_compatible",
            base_url="https://llm.example.invalid/v1",
            model="scripted-model",
            enabled=True,
            status="configured",
        )
        session.add(provider)
        await session.commit()
        provider_id = provider.id
    effective = _settings(settings, **updates)
    gateway = LLMGateway(
        database,
        effective,
        CredentialCipher(settings.credential_encryption_key or ""),
        BudgetService(database, effective),
    )
    return Env(gateway=gateway, database=database, provider_id=provider_id)


def _install(monkeypatch: pytest.MonkeyPatch, env: Env, adapter: BaseLLMProvider) -> None:
    monkeypatch.setattr(env.gateway, "_adapter_for", lambda record, require_model=True: adapter)


def _request(*, timeout_seconds: float = 5.0) -> LLMRequest:
    return LLMRequest(
        model="ignored",
        messages=[{"role": "user", "content": "你好"}],
        timeout_seconds=timeout_seconds,
        purpose="reply",
    )


async def _usage(database: Database, provider_id: str) -> list[LLMUsage]:
    async with database.session() as session:
        return list(
            (
                await session.execute(
                    select(LLMUsage).where(LLMUsage.provider_id == provider_id).order_by(LLMUsage.created_at)
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_rate_limit_retry_after_is_honored(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ScriptedAdapter(
        env.provider_id,
        [
            _error(
                ErrorCode.LLM_RATE_LIMITED,
                "限流",
                retryable=True,
                safety="safe",
                retry_after=0.01,
            ),
            LLMResponse(text="第二次成功", input_tokens=2, output_tokens=3, request_id="upstream-ok"),
        ],
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.generate(_request(), provider_id=env.provider_id)

    assert result.response.text == "第二次成功"
    assert result.attempts == 2
    assert adapter.calls == 2
    usage = await _usage(database, env.provider_id)
    assert [(item.status, item.error_code) for item in usage] == [
        ("error", ErrorCode.LLM_RATE_LIMITED),
        ("success", None),
    ]
    assert usage[-1].request_id == "upstream-ok"


@pytest.mark.asyncio
async def test_five_xx_retries_once_then_succeeds(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ScriptedAdapter(
        env.provider_id,
        [
            _error(ErrorCode.LLM_NETWORK_ERROR, "服务不可用", retryable=True, safety="safe"),
            LLMResponse(text="成功", input_tokens=1, output_tokens=1),
        ],
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.generate(_request(), provider_id=env.provider_id)

    assert result.response.text == "成功"
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_ambiguous_read_timeout_is_not_retried_by_default(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ScriptedAdapter(
        env.provider_id,
        [
            _error(ErrorCode.LLM_TIMEOUT, "读超时", retryable=True, safety="ambiguous"),
            LLMResponse(text="不应到达", input_tokens=1, output_tokens=1),
        ],
    )
    _install(monkeypatch, env, adapter)

    with pytest.raises(AppError) as caught:
        await env.gateway.generate(_request(), provider_id=env.provider_id)

    assert caught.value.code == ErrorCode.LLM_TIMEOUT
    assert caught.value.details["attempts"] == 1
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_ambiguous_timeout_can_be_retried_when_enabled(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings, llm_retry_ambiguous_timeouts=True)
    adapter = ScriptedAdapter(
        env.provider_id,
        [
            _error(ErrorCode.LLM_TIMEOUT, "读超时", retryable=True, safety="ambiguous"),
            LLMResponse(text="重试成功", input_tokens=1, output_tokens=1),
        ],
    )
    _install(monkeypatch, env, adapter)

    result = await env.gateway.generate(_request(), provider_id=env.provider_id)

    assert result.response.text == "重试成功"
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_auth_and_model_errors_are_not_retried(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for code in (ErrorCode.LLM_AUTH_FAILED, ErrorCode.LLM_MODEL_NOT_FOUND):
        env = await _env(database, settings)
        adapter = ScriptedAdapter(
            env.provider_id,
            [_error(code, "不可重试", retryable=False, safety="none")],
        )
        _install(monkeypatch, env, adapter)

        with pytest.raises(AppError) as caught:
            await env.gateway.generate(_request(), provider_id=env.provider_id)
        assert caught.value.code == code
        assert adapter.calls == 1


@pytest.mark.asyncio
async def test_retry_after_over_cap_is_not_waited(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings, llm_retry_after_max_seconds=1.0)
    adapter = ScriptedAdapter(
        env.provider_id,
        [
            _error(
                ErrorCode.LLM_RATE_LIMITED,
                "限流",
                retryable=True,
                safety="safe",
                retry_after=60.0,
            )
        ],
    )
    _install(monkeypatch, env, adapter)

    with pytest.raises(AppError) as caught:
        await env.gateway.generate(_request(), provider_id=env.provider_id)
    assert caught.value.code == ErrorCode.LLM_RATE_LIMITED
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_retries_are_bounded(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings, llm_max_retries=2)
    adapter = ScriptedAdapter(
        env.provider_id,
        [_error(ErrorCode.LLM_NETWORK_ERROR, "持续失败", retryable=True, safety="safe")],
    )
    _install(monkeypatch, env, adapter)

    with pytest.raises(AppError) as caught:
        await env.gateway.generate(_request(), provider_id=env.provider_id)

    assert caught.value.details["attempts"] == 3
    assert adapter.calls == 3


@pytest.mark.asyncio
async def test_wait_for_timeout_records_usage(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ScriptedAdapter(env.provider_id, [5.0])
    _install(monkeypatch, env, adapter)

    with pytest.raises(AppError) as caught:
        await env.gateway.generate(_request(timeout_seconds=0.05), provider_id=env.provider_id)

    assert caught.value.code == ErrorCode.LLM_TIMEOUT
    assert caught.value.details["retry_safety"] == "ambiguous"
    usage = await _usage(database, env.provider_id)
    assert usage[0].status == "error"
    assert usage[0].input_tokens is None
    assert usage[0].estimated_cost is None


@pytest.mark.asyncio
async def test_cancel_records_cancelled_usage_and_does_not_mark_provider_error(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await _env(database, settings)
    adapter = ScriptedAdapter(env.provider_id, [5.0])
    _install(monkeypatch, env, adapter)

    task = asyncio.create_task(
        env.gateway.test_provider(env.provider_id, kind="generation", operation_id="test-operation-1"),
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=2)
    assert env.gateway.cancel_operation(env.provider_id, "test-operation-1") is True

    result = await task
    assert result.outcome == "cancelled"
    assert result.ok is False
    assert result.error_code == ErrorCode.LLM_CANCELLED
    assert result.retryable is False

    usage = await _usage(database, env.provider_id)
    assert usage[0].status == "cancelled"
    assert usage[0].error_code == ErrorCode.LLM_CANCELLED
    assert usage[0].input_tokens is None
    assert usage[0].estimated_cost is None

    async with database.session() as session:
        provider = await session.get(LLMProvider, env.provider_id)
        assert provider is not None
        assert provider.status == "configured"


@pytest.mark.asyncio
async def test_limiter_enforces_concurrency_and_interval() -> None:
    clock_value = {"now": 100.0}
    sleeps: list[float] = []
    active = {"count": 0, "max": 0}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock_value["now"] += seconds

    limiter = ProviderLimiter(
        max_concurrency=1,
        min_interval_ms=200,
        clock=lambda: clock_value["now"],
        sleep=fake_sleep,
    )

    async def worker() -> None:
        async with limiter.slot("provider-a"):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            clock_value["now"] += 0.01
            active["count"] -= 1

    await asyncio.gather(worker(), worker())

    assert active["max"] == 1
    assert sleeps and abs(sleeps[0] - 0.19) < 0.001

    # Mock 不占用真实 Provider 配额，不应触发间隔等待。
    sleeps.clear()
    async with limiter.slot("provider-a", is_mock=True):
        pass
    assert sleeps == []
