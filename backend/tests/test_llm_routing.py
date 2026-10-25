"""群级模型路由与受控故障回退测试（不访问真实模型）。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from app.adapters.llm.base import BaseLLMProvider
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.account import Account
from app.models.governance import BudgetPolicy
from app.models.group import Group
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.llm_gateway import LLMGateway
from app.schemas.llm import ConnectionTestResult, LLMRequest, LLMResponse
from sqlalchemy import select


class ScriptedAdapter(BaseLLMProvider):
    """测试专用适配器：记录调用次数并按脚本成功或抛出分类错误。"""

    provider_type = "openai_compatible"

    def __init__(self, provider_id: str, *, error: AppError | None = None) -> None:
        super().__init__(provider_id=provider_id, name=f"scripted-{provider_id}", model="scripted-model")
        self.error = error
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(text="路由测试回复", input_tokens=7, output_tokens=5)

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="ok")


@dataclass
class RoutingEnv:
    database: Database
    settings: Settings
    gateway: LLMGateway
    budget: BudgetService
    account: Account
    group: Group
    default_provider: LLMProvider
    primary: LLMProvider
    fallback: LLMProvider


async def build_routing_env(
    database: Database,
    settings: Settings,
    *,
    bind: bool = True,
    primary_enabled: bool = True,
    fallback_enabled: bool = True,
) -> RoutingEnv:
    async with database.session() as session:
        account = Account(
            display_name="路由测试账号",
            platform="qq",
            adapter_type="mock",
            self_platform_user_id="10000",
            enabled=True,
        )
        session.add(account)
        await session.flush()
        default_provider = LLMProvider(
            name="默认 Mock",
            provider_type="mock",
            model="mock-model",
            enabled=True,
            is_default=True,
        )
        primary = LLMProvider(
            name="主模型",
            provider_type="openai_compatible",
            model="primary-model",
            enabled=primary_enabled,
        )
        fallback = LLMProvider(
            name="备用模型",
            provider_type="mock",
            model="fallback-model",
            enabled=fallback_enabled,
        )
        session.add_all([default_provider, primary, fallback])
        await session.flush()
        group = Group(
            account_id=account.id,
            platform_group_id="100001",
            name="路由测试群",
            enabled=True,
            reply_mode="mention_only",
            timezone="Asia/Shanghai",
            quiet_hours_json={},
            rate_limit_json={"cooldown_seconds": 0},
            keywords_json=[],
            admin_user_ids_json=[],
            llm_provider_id=primary.id if bind else None,
            llm_fallback_provider_id=fallback.id if bind else None,
        )
        session.add(group)
        await session.commit()
        for item in (account, default_provider, primary, fallback, group):
            await session.refresh(item)

    budget = BudgetService(database, settings)
    gateway = LLMGateway(
        database,
        settings,
        CredentialCipher(settings.credential_encryption_key or ""),
        budget,
    )
    return RoutingEnv(
        database=database,
        settings=settings,
        gateway=gateway,
        budget=budget,
        account=account,
        group=group,
        default_provider=default_provider,
        primary=primary,
        fallback=fallback,
    )


def request() -> LLMRequest:
    return LLMRequest(model="ignored", messages=[{"role": "user", "content": "你好"}])


def install_adapters(
    monkeypatch: pytest.MonkeyPatch,
    gateway: LLMGateway,
    adapters: dict[str, ScriptedAdapter],
) -> None:
    original = gateway._adapter_for

    def adapter_for(record: LLMProvider) -> BaseLLMProvider:
        return adapters.get(record.id) or original(record)

    monkeypatch.setattr(gateway, "_adapter_for", adapter_for)


@pytest.mark.asyncio
async def test_group_binding_routes_to_primary(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings)
    primary = ScriptedAdapter(env.primary.id)
    fallback = ScriptedAdapter(env.fallback.id)
    install_adapters(monkeypatch, env.gateway, {env.primary.id: primary, env.fallback.id: fallback})

    result = await env.gateway.generate(request(), group_id=env.group.id)

    assert result.provider_id == env.primary.id
    assert result.route_source == "group_binding"
    assert result.fallback_used is False
    assert result.primary_provider_id == env.primary.id
    assert result.primary_attempts == 1
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_unbound_group_uses_default_provider(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings, bind=False)
    default = ScriptedAdapter(env.default_provider.id)
    install_adapters(monkeypatch, env.gateway, {env.default_provider.id: default})

    result = await env.gateway.generate(request(), group_id=env.group.id)

    assert result.provider_id == env.default_provider.id
    assert result.route_source == "default"
    assert result.fallback_used is False
    assert default.calls == 1


@pytest.mark.asyncio
async def test_provider_error_falls_back_once_and_keeps_routes(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings)
    primary = ScriptedAdapter(
        env.primary.id,
        error=AppError(ErrorCode.LLM_TIMEOUT, "模拟主模型超时。", status_code=504),
    )
    fallback = ScriptedAdapter(env.fallback.id)
    install_adapters(monkeypatch, env.gateway, {env.primary.id: primary, env.fallback.id: fallback})

    result = await env.gateway.generate(request(), group_id=env.group.id)

    assert result.provider_id == env.fallback.id
    assert result.fallback_used is True
    assert result.primary_provider_id == env.primary.id
    assert result.primary_error_code == ErrorCode.LLM_TIMEOUT
    assert result.primary_attempts == 1
    assert result.route_source == "group_binding"
    assert primary.calls == 1
    assert fallback.calls == 1

    async with database.session() as session:
        usage = list(
            (
                await session.execute(
                    select(LLMUsage).where(LLMUsage.group_id == env.group.id).order_by(LLMUsage.created_at)
                )
            ).scalars()
        )
    assert [(item.provider_id, item.status) for item in usage] == [
        (env.primary.id, "error"),
        (env.fallback.id, "success"),
    ]


@pytest.mark.asyncio
async def test_fallback_is_not_retried_repeatedly(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings)
    primary = ScriptedAdapter(
        env.primary.id,
        error=AppError(ErrorCode.LLM_NETWORK_ERROR, "模拟主模型网络失败。", status_code=502),
    )
    fallback = ScriptedAdapter(
        env.fallback.id,
        error=AppError(ErrorCode.LLM_RATE_LIMITED, "模拟备用模型限流。", status_code=429),
    )
    install_adapters(monkeypatch, env.gateway, {env.primary.id: primary, env.fallback.id: fallback})

    with pytest.raises(AppError) as excinfo:
        await env.gateway.generate(request(), group_id=env.group.id)

    error = excinfo.value
    assert error.code == ErrorCode.LLM_RATE_LIMITED
    assert error.details["primary_error_code"] == ErrorCode.LLM_NETWORK_ERROR
    assert error.details["fallback_error_code"] == ErrorCode.LLM_RATE_LIMITED
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_does_not_fall_back(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings)
    primary = ScriptedAdapter(env.primary.id)
    fallback = ScriptedAdapter(env.fallback.id)
    install_adapters(monkeypatch, env.gateway, {env.primary.id: primary, env.fallback.id: fallback})
    await env.budget.record(provider_id=None, group_id=None, feature="reply", requests=1)
    async with database.session() as session:
        session.add(
            BudgetPolicy(
                scope_type="global",
                scope_id="",
                window="day",
                metric="requests",
                limit_value=1,
                enabled=True,
            )
        )
        await session.commit()

    with pytest.raises(AppError) as excinfo:
        await env.gateway.generate(request(), group_id=env.group.id)

    assert excinfo.value.code == ErrorCode.BUDGET_EXCEEDED
    assert primary.calls == 0
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_disabled_primary_does_not_fall_back(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await build_routing_env(database, settings, primary_enabled=False)
    fallback = ScriptedAdapter(env.fallback.id)
    install_adapters(monkeypatch, env.gateway, {env.fallback.id: fallback})

    with pytest.raises(AppError) as excinfo:
        await env.gateway.generate(request(), group_id=env.group.id)

    assert excinfo.value.code == ErrorCode.PROVIDER_DISABLED
    assert fallback.calls == 0
