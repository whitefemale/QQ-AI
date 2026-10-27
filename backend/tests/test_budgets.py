"""Provider / 群维度的真实用量聚合与费用预算执行。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from app.budgets.service import BudgetService, cost_status, provider_pricing_state
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.governance import AuditLog, UsageEvent
from app.models.group import Group
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.events import EventBus
from sqlalchemy import func, select


@dataclass
class Fixture:
    database: Database
    settings: Settings
    service: BudgetService
    events: EventBus
    group_a: Group
    group_b: Group
    priced: LLMProvider
    unpriced: LLMProvider
    mock: LLMProvider


@pytest.fixture
def service(database: Database, settings: Settings) -> BudgetService:
    return BudgetService(database, settings)


def _provider(
    provider_id: str,
    *,
    provider_type: str = "openai_compatible",
    config: dict[str, float] | None = None,
) -> LLMProvider:
    return LLMProvider(
        id=provider_id,
        name=f"Provider {provider_id}",
        provider_type=provider_type,
        model=f"model-{provider_id}",
        enabled=True,
        config_json=config or {},
    )


async def _seed(database: Database, settings: Settings) -> Fixture:
    async with database.session() as session:
        account = Account(id="acc-budget", display_name="预算测试账号", adapter_type="mock")
        session.add(account)
        await session.flush()
        group_a = Group(
            id="group-a",
            account_id=account.id,
            platform_group_id="90001",
            name="群 A",
            enabled=True,
        )
        group_b = Group(
            id="group-b",
            account_id=account.id,
            platform_group_id="90002",
            name="群 B",
            enabled=True,
        )
        priced = _provider("prov-priced", config={"input_price_per_1k": 1.0, "output_price_per_1k": 2.0})
        unpriced = _provider("prov-unpriced")
        mock = _provider("prov-mock", provider_type="mock", config={"input_price_per_1k": 99.0})
        session.add_all([group_a, group_b, priced, unpriced, mock])
        await session.commit()
    events = EventBus()
    return Fixture(
        database=database,
        settings=settings,
        service=BudgetService(database, settings, events=events),
        events=events,
        group_a=group_a,
        group_b=group_b,
        priced=priced,
        unpriced=unpriced,
        mock=mock,
    )


async def _add_usage(
    fx: Fixture,
    *,
    provider: LLMProvider,
    group: Group | None,
    status: str = "success",
    tokens: int = 100,
    cost: float | None = None,
    created_at: datetime | None = None,
) -> None:
    async with fx.database.session() as session:
        session.add(
            LLMUsage(
                provider_id=provider.id,
                provider_type=provider.provider_type,
                model=provider.model,
                group_id=group.id if group else None,
                input_tokens=tokens // 2,
                output_tokens=tokens - tokens // 2,
                total_tokens=tokens,
                estimated_cost=cost,
                status=status,
                purpose="reply",
                created_at=created_at or utcnow(),
            )
        )
        await session.commit()


def test_pricing_and_cost_status_helpers() -> None:
    assert provider_pricing_state(_provider("p", config={"input_price_per_1k": 0.5})) == "configured"
    assert provider_pricing_state(_provider("p")) == "unconfigured"
    assert provider_pricing_state(_provider("p", provider_type="mock")) == "mock_zero"
    assert provider_pricing_state(None) == "unconfigured"

    assert cost_status(0, 0, 0) == "no_calls"
    assert cost_status(2, 2, 0) == "complete"
    assert cost_status(2, 2, 2) == "not_applicable"
    assert cost_status(2, 1, 0) == "partial"
    assert cost_status(2, 0, 0) == "unconfigured"


async def test_usage_summary_aggregates_by_provider_and_group(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    await _add_usage(fx, provider=fx.priced, group=fx.group_a, tokens=100, cost=0.05)
    await _add_usage(fx, provider=fx.unpriced, group=fx.group_b, tokens=50)
    await _add_usage(fx, provider=fx.mock, group=fx.group_b, tokens=30)
    await _add_usage(fx, provider=fx.unpriced, group=fx.group_a, status="error", tokens=0)

    summary = await fx.service.usage_summary(hours=24)

    assert summary["requests"] == 4
    assert summary["successful_requests"] == 3
    assert summary["failed_requests"] == 1
    assert summary["tokens"] == 180
    assert summary["priced_success_requests"] == 2
    assert summary["unpriced_success_requests"] == 1
    assert summary["cost"] == pytest.approx(0.05)
    assert summary["cost_status"] == "partial"
    assert summary["currency"] == "USD"

    by_provider = {item["provider_id"]: item for item in summary["by_provider"]}
    assert set(by_provider) == {"prov-priced", "prov-unpriced", "prov-mock"}
    assert by_provider["prov-priced"]["requests"] == 1
    assert by_provider["prov-priced"]["cost_status"] == "complete"
    assert by_provider["prov-unpriced"]["requests"] == 2
    assert by_provider["prov-unpriced"]["failed_requests"] == 1
    assert by_provider["prov-unpriced"]["cost"] is None
    assert by_provider["prov-unpriced"]["cost_status"] == "unconfigured"
    assert by_provider["prov-unpriced"]["cost_tracking"] == "unconfigured"
    assert by_provider["prov-mock"]["cost_status"] == "not_applicable"
    assert by_provider["prov-mock"]["is_mock"] is True

    by_group = {item["group_id"]: item for item in summary["by_group"]}
    assert set(by_group) == {"group-a", "group-b"}
    assert by_group["group-a"]["requests"] == 2
    assert by_group["group-a"]["successful_requests"] == 1
    assert by_group["group-a"]["cost"] == pytest.approx(0.05)
    assert by_group["group-a"]["cost_status"] == "complete"
    assert by_group["group-b"]["requests"] == 2
    assert by_group["group-b"]["cost_status"] == "partial"
    assert by_group["group-b"]["unpriced_success_requests"] == 1


async def test_usage_summary_never_fabricates_cost_for_unpriced_provider(
    database: Database, settings: Settings
) -> None:
    fx = await _seed(database, settings)
    await _add_usage(fx, provider=fx.unpriced, group=fx.group_a, tokens=80)

    summary = await fx.service.usage_summary(hours=1)

    assert summary["requests"] == 1
    assert summary["cost"] is None
    assert summary["cost_status"] == "unconfigured"
    assert summary["unpriced_success_requests"] == 1


async def test_usage_summary_excludes_records_outside_window(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    async with fx.database.session() as session:
        session.add(
            LLMUsage(
                provider_id=fx.priced.id,
                provider_type=fx.priced.provider_type,
                group_id=fx.group_a.id,
                total_tokens=100,
                estimated_cost=0.05,
                status="success",
                created_at=utcnow() - timedelta(days=3),
            )
        )
        await session.commit()

    summary = await fx.service.usage_summary(hours=24)

    assert summary["requests"] == 0
    assert summary["cost"] is None
    assert summary["cost_status"] == "no_calls"
    assert summary["by_provider"][0]["requests"] == 0


async def test_group_cost_budget_is_isolated_between_groups(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    await fx.service.upsert_policy(
        {"scope_type": "group", "scope_id": fx.group_a.id, "window": "day", "metric": "cost", "limit_value": 0.1}
    )
    await fx.service.record(
        provider_id=fx.priced.id,
        group_id=fx.group_a.id,
        feature="reply",
        tokens=100,
        estimated_cost=0.1,
    )

    blocked = await fx.service.check(group_id=fx.group_a.id, provider_id=fx.priced.id)
    assert blocked.allowed is False
    assert blocked.blocks[0].scope_type == "group"
    assert blocked.blocks[0].scope_id == fx.group_a.id
    assert blocked.blocks[0].metric == "cost"
    assert blocked.blocks[0].reason == "limit_reached"

    other_group = await fx.service.check(group_id=fx.group_b.id, provider_id=fx.priced.id)
    assert other_group.allowed is True

    with pytest.raises(AppError) as excinfo:
        await fx.service.assert_allowed(group_id=fx.group_a.id, provider_id=fx.priced.id)
    assert excinfo.value.code == ErrorCode.BUDGET_EXCEEDED
    assert excinfo.value.status_code == 429
    assert excinfo.value.details is not None
    assert excinfo.value.details["reason"] == "limit_reached"


async def test_provider_cost_budget_is_isolated_between_providers(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    await fx.service.upsert_policy(
        {
            "scope_type": "provider",
            "scope_id": fx.priced.id,
            "window": "day",
            "metric": "cost",
            "limit_value": 0.05,
        }
    )
    await fx.service.record(
        provider_id=fx.priced.id,
        group_id=fx.group_a.id,
        feature="reply",
        tokens=100,
        estimated_cost=0.05,
    )

    same_provider_other_group = await fx.service.check(group_id=fx.group_b.id, provider_id=fx.priced.id)
    assert same_provider_other_group.allowed is False
    assert same_provider_other_group.blocks[0].scope_type == "provider"

    other_provider = await fx.service.check(group_id=fx.group_a.id, provider_id=fx.mock.id)
    assert other_provider.allowed is True


async def test_global_cost_budget_blocks_unpriced_but_allows_mock_and_priced(
    database: Database, settings: Settings
) -> None:
    fx = await _seed(database, settings)
    await fx.service.upsert_policy(
        {"scope_type": "global", "scope_id": "", "window": "day", "metric": "cost", "limit_value": 1.0}
    )

    unpriced = await fx.service.check(group_id=fx.group_a.id, provider_id=fx.unpriced.id)
    assert unpriced.allowed is False
    assert unpriced.blocks[0].reason == "cost_unavailable"
    assert unpriced.blocks[0].used == 0

    with pytest.raises(AppError) as excinfo:
        await fx.service.assert_allowed(group_id=fx.group_a.id, provider_id=fx.unpriced.id)
    assert excinfo.value.code == ErrorCode.BUDGET_EXCEEDED
    assert excinfo.value.details is not None
    assert excinfo.value.details["reason"] == "cost_unavailable"
    assert "未配置" in excinfo.value.message

    assert (await fx.service.check(group_id=fx.group_a.id, provider_id=fx.mock.id)).allowed is True
    assert (await fx.service.check(group_id=fx.group_a.id, provider_id=fx.priced.id)).allowed is True


async def test_policy_snapshot_reports_real_usage_state_and_cost_completeness(
    database: Database, settings: Settings
) -> None:
    fx = await _seed(database, settings)
    policy = await fx.service.upsert_policy(
        {
            "scope_type": "group",
            "scope_id": fx.group_a.id,
            "window": "day",
            "metric": "cost",
            "limit_value": 0.1,
            "warn_threshold": 0.8,
        }
    )
    await fx.service.record(
        provider_id=fx.priced.id,
        group_id=fx.group_a.id,
        feature="reply",
        tokens=100,
        estimated_cost=0.08,
    )
    await _add_usage(fx, provider=fx.priced, group=fx.group_a, tokens=100, cost=0.08)
    await _add_usage(fx, provider=fx.unpriced, group=fx.group_a, tokens=20)

    snapshot = await fx.service.get_policy(policy["id"])

    assert snapshot["used"] == pytest.approx(0.08)
    assert snapshot["remaining"] == pytest.approx(0.02)
    assert snapshot["usage_ratio"] == pytest.approx(0.8)
    assert snapshot["state"] == "warning"
    assert snapshot["cost_status"] == "partial"
    assert snapshot["unpriced_success_requests"] == 1

    await fx.service.record(
        provider_id=fx.priced.id,
        group_id=fx.group_a.id,
        feature="reply",
        tokens=50,
        estimated_cost=0.03,
    )
    exceeded = await fx.service.get_policy(policy["id"])
    assert exceeded["state"] == "exceeded"
    assert exceeded["remaining"] == 0.0


async def test_budget_policy_rejects_unknown_scope_target(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)

    with pytest.raises(AppError) as excinfo:
        await fx.service.upsert_policy(
            {"scope_type": "group", "scope_id": "missing-group", "window": "day", "metric": "requests"}
        )
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert excinfo.value.status_code == 400

    with pytest.raises(AppError) as excinfo:
        await fx.service.upsert_policy(
            {"scope_type": "provider", "scope_id": "missing-provider", "window": "day", "metric": "cost"}
        )
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


async def test_usage_trends_use_real_records_and_keep_unknown_cost_null(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    now = utcnow()
    await _add_usage(
        fx,
        provider=fx.priced,
        group=fx.group_a,
        tokens=100,
        cost=0.05,
        created_at=now - timedelta(minutes=30),
    )
    await _add_usage(
        fx,
        provider=fx.unpriced,
        group=fx.group_a,
        tokens=50,
        created_at=now - timedelta(hours=2),
    )
    await _add_usage(
        fx,
        provider=fx.mock,
        group=fx.group_a,
        tokens=30,
        created_at=now - timedelta(days=1, hours=1),
    )

    hourly = await fx.service.usage_trends(bucket="hour", periods=24, group_id=fx.group_a.id)

    assert hourly["bucket"] == "hour"
    assert hourly["periods"] == 24
    assert hourly["timezone"] == settings.default_timezone
    assert len(hourly["items"]) == 24
    assert hourly["requests"] == 2
    assert hourly["tokens"] == 150
    assert hourly["cost"] == pytest.approx(0.05)
    assert hourly["cost_status"] == "partial"
    assert hourly["unpriced_success_requests"] == 1
    assert sum(item["requests"] for item in hourly["items"]) == 2
    # 已配置单价的调用有费用，未配置单价的调用仍为 None，两者不混淆。
    assert sum(item["cost"] or 0 for item in hourly["items"]) == pytest.approx(0.05)
    assert any(item["requests"] > 0 and item["cost"] is None for item in hourly["items"])

    daily = await fx.service.usage_trends(bucket="day", periods=3, group_id=fx.group_a.id)
    assert len(daily["items"]) == 3
    assert daily["requests"] == 3
    assert daily["tokens"] == 180
    assert daily["cost"] == pytest.approx(0.05)
    assert daily["cost_status"] == "partial"

    priced_only = await fx.service.usage_trends(bucket="day", periods=3, provider_id=fx.priced.id)
    assert priced_only["requests"] == 1
    assert priced_only["cost_status"] == "complete"

    no_data = await fx.service.usage_trends(bucket="hour", periods=24, group_id=fx.group_b.id)
    assert no_data["requests"] == 0
    assert no_data["cost"] is None
    assert no_data["cost_status"] == "no_calls"
    assert all(item["cost"] is None for item in no_data["items"])


async def test_usage_trends_reject_invalid_bucket_and_periods(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)

    with pytest.raises(AppError) as excinfo:
        await fx.service.usage_trends(bucket="minute", periods=24)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppError) as excinfo:
        await fx.service.usage_trends(bucket="hour", periods=0)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


async def test_budget_alerts_warn_then_exceed_once_and_write_audit(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    policy = await fx.service.upsert_policy(
        {
            "scope_type": "global",
            "scope_id": "",
            "window": "day",
            "metric": "requests",
            "limit_value": 10,
            "warn_threshold": 0.5,
        }
    )

    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        feature="reply",
        requests=5,
    )
    first = await fx.service.list_alerts()
    assert first["total"] == 1
    assert first["items"][0]["policy_id"] == policy["id"]
    assert first["items"][0]["level"] == "warning"
    assert first["items"][0]["used"] == 5
    assert first["items"][0]["scope_name"] == "全局"
    assert "告警阈值" in first["items"][0]["message"]
    assert first["note"]

    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        feature="reply",
        requests=5,
    )
    second = await fx.service.list_alerts()
    assert second["total"] == 2
    assert {item["level"] for item in second["items"]} == {"warning", "exceeded"}

    # 同一周期继续记录用量不会重复生成事件。
    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        feature="reply",
        requests=1,
    )
    third = await fx.service.list_alerts()
    assert third["total"] == 2

    exceeded_only = await fx.service.list_alerts(level="exceeded")
    assert exceeded_only["total"] == 1

    async with fx.database.session() as session:
        audit_count = await session.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action.like("budget.alert.%"))
        )
    assert audit_count == 2

    published = [event for event in fx.events.recent(20) if event["type"] == "budget.alert"]
    assert len(published) == 2
    assert {event["payload"]["level"] for event in published} == {"warning", "exceeded"}


async def test_upsert_policy_alerts_on_existing_usage(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        feature="reply",
        requests=5,
    )
    assert (await fx.service.list_alerts())["total"] == 0

    await fx.service.upsert_policy(
        {
            "scope_type": "global",
            "scope_id": "",
            "window": "day",
            "metric": "requests",
            "limit_value": 5,
            "warn_threshold": 0.5,
        }
    )

    alerts = await fx.service.list_alerts()
    assert alerts["total"] == 1
    assert alerts["items"][0]["level"] == "exceeded"


async def test_account_and_feature_scopes_block_and_record(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    account_policy = await fx.service.upsert_policy(
        {
            "scope_type": "account",
            "scope_id": "acc-budget",
            "window": "day",
            "metric": "requests",
            "limit_value": 1,
            "warn_threshold": 0.8,
        }
    )
    feature_policy = await fx.service.upsert_policy(
        {
            "scope_type": "feature",
            "scope_id": "chat",
            "window": "all",
            "metric": "requests",
            "limit_value": 1,
            "warn_threshold": 0.8,
        }
    )
    assert account_policy["scope_type"] == "account"
    assert feature_policy["scope_type"] == "feature"

    # 旧 purpose=reply 在预算层归一化为 chat，且同时记入账号与功能用量。
    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        account_id="acc-budget",
        feature="reply",
        requests=1,
    )

    check = await fx.service.check(
        group_id=fx.group_a.id,
        provider_id=fx.mock.id,
        account_id="acc-budget",
        feature="chat",
    )
    assert check.allowed is False
    assert {block.scope_type for block in check.blocks} == {"account", "feature"}

    with pytest.raises(AppError) as exc_info:
        await fx.service.assert_allowed(
            group_id=fx.group_a.id,
            provider_id=fx.mock.id,
            account_id="acc-budget",
            feature="reply",
        )
    assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED

    # 其它账号、其它功能不受这两个作用域影响（仍会受全局策略影响，此处没有全局策略）。
    other = await fx.service.check(
        group_id=fx.group_a.id,
        provider_id=fx.mock.id,
        account_id="acc-other",
        feature="persona_growth",
    )
    assert other.allowed is True

    alerts = await fx.service.list_alerts()
    assert alerts["total"] >= 2
    names = {item["scope_name"] for item in alerts["items"]}
    assert "预算测试账号" in names
    assert "聊天回复" in names


async def test_feature_scope_rejects_unknown_key_and_missing_account(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    with pytest.raises(AppError) as feature_error:
        await fx.service.upsert_policy(
            {
                "scope_type": "feature",
                "scope_id": "arbitrary-prompt-text",
                "window": "day",
                "metric": "requests",
                "limit_value": 1,
            }
        )
    assert feature_error.value.code == ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppError) as account_error:
        await fx.service.upsert_policy(
            {
                "scope_type": "account",
                "scope_id": "missing-account",
                "window": "day",
                "metric": "requests",
                "limit_value": 1,
            }
        )
    assert account_error.value.code == ErrorCode.VALIDATION_ERROR


async def test_unknown_feature_usage_is_recorded_but_not_matched(database: Database, settings: Settings) -> None:
    fx = await _seed(database, settings)
    await fx.service.upsert_policy(
        {
            "scope_type": "feature",
            "scope_id": "chat",
            "window": "all",
            "metric": "requests",
            "limit_value": 1,
        }
    )
    await fx.service.record(
        provider_id=fx.mock.id,
        group_id=fx.group_a.id,
        feature="custom_unlisted_feature",
        requests=1,
    )
    check = await fx.service.check(
        group_id=fx.group_a.id,
        provider_id=fx.mock.id,
        feature="custom_unlisted_feature",
    )
    assert check.allowed is True

    async with fx.database.session() as session:
        feature_rows = await session.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.scope_type == "feature"))
        total_rows = await session.scalar(select(func.count(UsageEvent.id)))
    # 未列入固定键的功能仍记录全局/群/Provider 用量，但不会生成 feature 作用域行。
    assert feature_rows == 0
    assert int(total_rows or 0) > 0
