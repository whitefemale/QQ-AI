"""预算与用量：全局 / 账号 / 群 / Provider / 功能作用域的调用前硬上限与调用后用量。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import (
    ensure_utc,
    get_zone,
    iso_utc,
    start_of_day_utc,
    start_of_month_utc,
    start_of_week_utc,
    utcnow,
)
from app.db.session import Database
from app.models.account import Account
from app.models.governance import BudgetAlert, BudgetPolicy, UsageEvent
from app.models.group import Group
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.events import EventBus
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

Window = Literal["hour", "day", "week", "month", "all"]
Metric = Literal["requests", "tokens", "cost"]

SUPPORTED_WINDOWS = {"hour", "day", "week", "month", "all"}
SUPPORTED_METRICS = {"requests", "tokens", "cost"}
SUPPORTED_SCOPES = {"global", "account", "group", "provider", "feature"}
TREND_BUCKETS = {"hour", "day"}

# 预算与用量中的固定功能键。模型请求内部的 purpose 仍是自由文本（如 reply），
# 只在预算层归一化为固定键，避免任意文本成为作用域 ID。
FEATURE_KEYS = {
    "chat": "聊天回复",
    "provider_test": "模型测试",
    "persona_growth": "人格成长",
    "memory_extraction": "记忆提取",
    "media.image.describe": "图片描述",
    "media.ocr.extract": "OCR 文字识别",
    "media.audio.transcribe": "语音转写",
    "media.text.embed": "文本向量",
    "media.inspect": "媒体检查",
    "media.text.rerank": "文本重排",
    "media.video.describe": "视频理解",
}
FEATURE_ALIASES = {"reply": "chat"}


def normalize_feature_key(feature: str | None) -> str | None:
    """把历史或内部用途名归一化为固定功能键；未知值保持原样但不会匹配功能预算。"""
    if feature is None:
        return None
    key = str(feature).strip()
    if not key:
        return None
    return FEATURE_ALIASES.get(key, key)


def feature_label(feature: str | None) -> str:
    key = normalize_feature_key(feature)
    if not key:
        return "未指定功能"
    return FEATURE_KEYS.get(key, key)


WINDOW_LABELS = {
    "hour": "每小时",
    "day": "每日",
    "week": "每周",
    "month": "每月",
    "all": "累计",
}
METRIC_LABELS = {
    "requests": "请求次数",
    "tokens": "Token 用量",
    "cost": "费用",
}
SCOPE_LABELS = {
    "global": "全局",
    "account": "账号",
    "group": "群",
    "provider": "模型 Provider",
    "feature": "功能",
}
ALERT_LEVEL_LABELS = {
    "warning": "接近上限",
    "exceeded": "已超限",
}

COST_NOTE = (
    "成本按你在 Provider 中填写的输入/输出单价与本地记录的 Token 估算，不是服务商账单。"
    "未配置单价的成功调用无法计入成本；Mock 调用的外部费用视为 0。"
)
ALERT_NOTE = (
    "告警按策略统计周期去重：同一周期最多各记一条「接近上限」和「已超限」事件。"
    "每次新事件同时写入审计日志（budget.alert.*）并发布 SSE 事件。"
    "费用预算因 Provider 未配置单价而阻断时，不生成告警事件，可在预算检查中查看阻断原因。"
)

# 费用数据完整性：complete 表示窗口内所有成功调用都有可估算费用；
# partial 表示部分 Provider 未配置单价；not_applicable 表示只有 Mock（无外部费用）。
COST_STATUS_COMPLETE = "complete"
COST_STATUS_PARTIAL = "partial"
COST_STATUS_UNCONFIGURED = "unconfigured"
COST_STATUS_NOT_APPLICABLE = "not_applicable"
COST_STATUS_NO_CALLS = "no_calls"


@dataclass
class BudgetBlock:
    policy_id: str
    scope_type: str
    scope_id: str
    window: str
    metric: str
    limit: float
    used: float
    reason: str = "limit_reached"

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "window": self.window,
            "metric": self.metric,
            "limit": self.limit,
            "used": self.used,
            "reason": self.reason,
        }


@dataclass
class BudgetCheck:
    allowed: bool
    blocks: list[BudgetBlock] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocks": [block.as_dict() for block in self.blocks],
            "note": (
                "预算按已记录的本地用量执行；单次调用可能使累计用量略超上限。"
                "费用预算要求当前 Provider 配置输入/输出单价（Mock 视为零外部费用），"
                "否则为避免无法计费的调用绕过上限，会直接阻断。"
            ),
        }


def window_start(window: str, timezone_name: str, now: datetime | None = None) -> datetime | None:
    now = now or utcnow()
    if window == "hour":
        return now - timedelta(hours=1)
    if window == "day":
        return start_of_day_utc(now, timezone_name)
    if window == "week":
        return start_of_week_utc(now, timezone_name)
    if window == "month":
        return start_of_month_utc(now, timezone_name)
    return None


def _price_values(config: dict[str, Any] | None) -> tuple[float, float]:
    raw = config or {}
    try:
        input_price = float(raw.get("input_price_per_1k", 0) or 0)
        output_price = float(raw.get("output_price_per_1k", 0) or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0
    return max(0.0, input_price), max(0.0, output_price)


def provider_pricing_state(record: LLMProvider | None) -> str:
    """返回 Provider 费用估算能力：mock_zero / configured / unconfigured。"""
    if record is None:
        return COST_STATUS_UNCONFIGURED
    if record.provider_type == "mock":
        return "mock_zero"
    input_price, output_price = _price_values(record.config_json)
    return "configured" if input_price > 0 or output_price > 0 else COST_STATUS_UNCONFIGURED


def cost_status(successes: int, priced: int, mock_successes: int) -> str:
    if successes <= 0:
        return COST_STATUS_NO_CALLS
    if priced >= successes:
        return COST_STATUS_NOT_APPLICABLE if mock_successes >= successes else COST_STATUS_COMPLETE
    if priced <= 0:
        return COST_STATUS_UNCONFIGURED
    return COST_STATUS_PARTIAL


def _cost_value(known_cost: float, priced: int) -> float | None:
    return None if priced <= 0 else round(known_cost, 8)


def _aggregate_query(key: Any, since: datetime, until: datetime) -> Any:
    success = LLMUsage.status == "success"
    known_cost = or_(LLMUsage.estimated_cost.is_not(None), LLMUsage.provider_type == "mock")
    mock_success = and_(success, LLMUsage.provider_type == "mock")
    return (
        select(
            key.label("bucket"),
            func.count(LLMUsage.id).label("requests"),
            func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(LLMUsage.estimated_cost), 0.0).label("cost"),
            func.coalesce(func.sum(case((success, 1), else_=0)), 0).label("successes"),
            func.coalesce(func.sum(case((and_(success, known_cost), 1), else_=0)), 0).label("priced"),
            func.coalesce(func.sum(case((mock_success, 1), else_=0)), 0).label("mock_successes"),
        )
        .where(LLMUsage.created_at >= since, LLMUsage.created_at <= until)
        .group_by(key)
    )


def _bucket_values(row: Any) -> dict[str, Any]:
    requests = int(row.requests or 0)
    successes = int(row.successes or 0)
    priced = int(row.priced or 0)
    mock_successes = int(row.mock_successes or 0)
    return {
        "requests": requests,
        "successful_requests": successes,
        "failed_requests": max(0, requests - successes),
        "tokens": int(row.tokens or 0),
        "cost": _cost_value(float(row.cost or 0.0), priced),
        "currency": "USD",
        "priced_success_requests": priced,
        "unpriced_success_requests": max(0, successes - priced),
        "cost_status": cost_status(successes, priced, mock_successes),
    }


def _empty_bucket() -> dict[str, Any]:
    return {
        "requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "tokens": 0,
        "cost": None,
        "currency": "USD",
        "priced_success_requests": 0,
        "unpriced_success_requests": 0,
        "cost_status": COST_STATUS_NO_CALLS,
    }


def _accumulator() -> dict[str, Any]:
    return {
        "requests": 0,
        "successes": 0,
        "priced": 0,
        "mock_successes": 0,
        "tokens": 0,
        "cost": 0.0,
    }


def _add_to_accumulator(
    bucket: dict[str, Any],
    *,
    status: str,
    total_tokens: int | None,
    estimated_cost: float | None,
    provider_type: str,
) -> None:
    bucket["requests"] += 1
    bucket["tokens"] += int(total_tokens or 0)
    if status != "success":
        return
    bucket["successes"] += 1
    known_cost = estimated_cost is not None or provider_type == "mock"
    if not known_cost:
        return
    bucket["priced"] += 1
    bucket["cost"] += float(estimated_cost or 0.0)
    if provider_type == "mock":
        bucket["mock_successes"] += 1


def _finalize_accumulator(bucket: dict[str, Any]) -> dict[str, Any]:
    requests = int(bucket["requests"])
    successes = int(bucket["successes"])
    priced = int(bucket["priced"])
    return {
        "requests": requests,
        "successful_requests": successes,
        "failed_requests": max(0, requests - successes),
        "tokens": int(bucket["tokens"]),
        "cost": _cost_value(float(bucket["cost"]), priced),
        "currency": "USD",
        "priced_success_requests": priced,
        "unpriced_success_requests": max(0, successes - priced),
        "cost_status": cost_status(successes, priced, int(bucket["mock_successes"])),
    }


class BudgetService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        events: EventBus | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.events = events

    def _applicable_scope(
        self,
        policy: BudgetPolicy,
        group_id: str | None,
        provider_id: str | None,
        account_id: str | None = None,
        feature: str | None = None,
    ) -> bool:
        if policy.scope_type == "global":
            return True
        if policy.scope_type == "account":
            return bool(account_id) and policy.scope_id == account_id
        if policy.scope_type == "group":
            return bool(group_id) and policy.scope_id == group_id
        if policy.scope_type == "provider":
            return bool(provider_id) and policy.scope_id == provider_id
        if policy.scope_type == "feature":
            normalized = normalize_feature_key(feature)
            return bool(normalized) and policy.scope_id == normalized
        return False

    async def _usage(self, policy: BudgetPolicy, start: datetime | None) -> float:
        async with self.database.session() as session:
            query = select(func.coalesce(func.sum(UsageEvent.amount), 0.0)).where(
                UsageEvent.scope_type == policy.scope_type,
                UsageEvent.scope_id == (policy.scope_id or ""),
                UsageEvent.metric == policy.metric,
            )
            if start is not None:
                query = query.where(UsageEvent.created_at >= start)
            used = await session.scalar(query)
        return float(used or 0.0)

    async def _cost_tracking_available(self, provider_id: str) -> bool:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
        return provider_pricing_state(record) in {"configured", "mock_zero"}

    async def check(
        self,
        *,
        group_id: str | None,
        provider_id: str | None,
        account_id: str | None = None,
        feature: str | None = None,
    ) -> BudgetCheck:
        async with self.database.session() as session:
            policies = list(
                (await session.execute(select(BudgetPolicy).where(BudgetPolicy.enabled.is_(True)))).scalars()
            )
        cost_tracking = await self._cost_tracking_available(provider_id) if provider_id else None
        blocks: list[BudgetBlock] = []
        for policy in policies:
            if not self._applicable_scope(policy, group_id, provider_id, account_id, feature):
                continue
            if policy.limit_value <= 0:
                continue
            start = window_start(policy.window, self.settings.default_timezone)
            used = await self._usage(policy, start)
            if used >= policy.limit_value:
                reason = "limit_reached"
            elif policy.metric == "cost" and cost_tracking is False:
                # 费用上限必须能计算每次调用的成本；未配置单价时若继续调用，
                # 费用会被记为未知，从而绕过上限。这里宁可阻断，也不伪造成本。
                reason = "cost_unavailable"
            else:
                continue
            blocks.append(
                BudgetBlock(
                    policy_id=policy.id,
                    scope_type=policy.scope_type,
                    scope_id=policy.scope_id,
                    window=policy.window,
                    metric=policy.metric,
                    limit=policy.limit_value,
                    used=used,
                    reason=reason,
                )
            )
        return BudgetCheck(allowed=not blocks, blocks=blocks)

    async def assert_allowed(
        self,
        *,
        group_id: str | None,
        provider_id: str | None,
        account_id: str | None = None,
        feature: str | None = None,
    ) -> None:
        check = await self.check(
            group_id=group_id,
            provider_id=provider_id,
            account_id=account_id,
            feature=feature,
        )
        if not check.allowed:
            first = check.blocks[0]
            if first.reason == "cost_unavailable":
                message = (
                    "费用预算已启用，但当前模型 Provider 未配置输入/输出 Token 单价，"
                    "无法估算本次费用，已阻断调用。请先在「模型 API」配置单价，或停用该费用预算。"
                )
            else:
                scope_label = SCOPE_LABELS.get(first.scope_type, first.scope_type)
                if first.scope_type == "feature":
                    scope_label = f"功能「{feature_label(first.scope_id)}」"
                metric_label = METRIC_LABELS.get(first.metric, first.metric)
                message = f"{scope_label}预算已用尽（{metric_label}，上限 {first.limit:g}）。本次调用已阻断。"
            raise AppError(
                ErrorCode.BUDGET_EXCEEDED,
                message,
                status_code=429,
                details={
                    "reason": first.reason,
                    "blocks": [block.as_dict() for block in check.blocks],
                },
            )

    def _period_key(self, policy: BudgetPolicy, now: datetime, zone: ZoneInfo) -> str:
        """生成稳定的统计周期键，用于告警去重。

        小时预算使用滚动窗口，不能直接用窗口起点做键（每分钟都在变化）；
        因此按当前本地小时去重，其余窗口按本地日/周/月对齐。
        """
        if policy.window == "all":
            return "all"
        if policy.window == "hour":
            return f"hour:{now.astimezone(zone).strftime('%Y-%m-%dT%H')}"
        start = window_start(policy.window, self.settings.default_timezone, now)
        assert start is not None
        local = start.astimezone(zone)
        if policy.window == "day":
            return f"day:{local.strftime('%Y-%m-%d')}"
        if policy.window == "week":
            return f"week:{local.strftime('%G-W%V')}"
        return f"month:{local.strftime('%Y-%m')}"

    @staticmethod
    def _alert_level(policy: BudgetPolicy, used: float) -> str | None:
        if not policy.enabled or policy.limit_value <= 0:
            return None
        if used >= policy.limit_value:
            return "exceeded"
        ratio = used / policy.limit_value
        if policy.warn_threshold > 0 and round(ratio, 6) >= policy.warn_threshold:
            return "warning"
        return None

    def _alert_message(self, policy: BudgetPolicy, level: str, used: float) -> str:
        scope = SCOPE_LABELS.get(policy.scope_type, policy.scope_type)
        window = WINDOW_LABELS.get(policy.window, policy.window)
        metric = METRIC_LABELS.get(policy.metric, policy.metric)
        ratio = used / policy.limit_value if policy.limit_value > 0 else 0.0
        if level == "exceeded":
            state = "已用尽"
        else:
            state = f"达到告警阈值 {policy.warn_threshold:.0%}"
        return f"{scope}预算（{window} / {metric}）{state}：已用 {used:g}，上限 {policy.limit_value:g}（{ratio:.1%}）。"

    async def _create_alert(
        self,
        *,
        policy: BudgetPolicy,
        level: str,
        used: float,
        period_key: str,
        period_start: datetime | None,
    ) -> dict[str, Any] | None:
        ratio = used / policy.limit_value if policy.limit_value > 0 else 0.0
        message = self._alert_message(policy, level, used)
        async with self.database.session() as session:
            exists = await session.scalar(
                select(BudgetAlert.id).where(
                    BudgetAlert.policy_id == policy.id,
                    BudgetAlert.period_key == period_key,
                    BudgetAlert.level == level,
                )
            )
            if exists is not None:
                return None
            alert = BudgetAlert(
                policy_id=policy.id,
                scope_type=policy.scope_type,
                scope_id=policy.scope_id,
                window=policy.window,
                metric=policy.metric,
                level=level,
                period_key=period_key,
                period_start=period_start,
                used_value=round(used, 8),
                limit_value=policy.limit_value,
                warn_threshold=policy.warn_threshold,
                usage_ratio=round(ratio, 6),
                message=message,
            )
            session.add(alert)
            try:
                await session.commit()
            except IntegrityError:
                # 并发调用可能同时越过阈值；唯一约束保证只保留一条。
                await session.rollback()
                return None
            await session.refresh(alert)
        public = {
            "id": alert.id,
            "policy_id": policy.id,
            "scope_type": policy.scope_type,
            "scope_id": policy.scope_id,
            "window": policy.window,
            "metric": policy.metric,
            "level": level,
            "period_key": period_key,
            "period_start": iso_utc(period_start),
            "used": round(used, 8),
            "limit": policy.limit_value,
            "warn_threshold": policy.warn_threshold,
            "usage_ratio": round(ratio, 6),
            "message": message,
            "created_at": iso_utc(alert.created_at),
        }
        await write_audit(
            self.database,
            action=f"budget.alert.{level}",
            target_type="budget_policy",
            target_id=policy.id,
            details={
                "scope_type": policy.scope_type,
                "scope_id": policy.scope_id,
                "window": policy.window,
                "metric": policy.metric,
                "used": round(used, 8),
                "limit": policy.limit_value,
                "usage_ratio": round(ratio, 6),
                "period_key": period_key,
            },
            actor="system",
        )
        if self.events is not None:
            self.events.publish("budget.alert", public)
        return public

    async def _evaluate_alerts(
        self,
        *,
        group_id: str | None,
        provider_id: str | None,
        account_id: str | None = None,
        feature: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            policies = list(
                (await session.execute(select(BudgetPolicy).where(BudgetPolicy.enabled.is_(True)))).scalars()
            )
        now = utcnow()
        zone = get_zone(self.settings.default_timezone)
        created: list[dict[str, Any]] = []
        for policy in policies:
            if not self._applicable_scope(policy, group_id, provider_id, account_id, feature):
                continue
            if policy.limit_value <= 0:
                continue
            start = window_start(policy.window, self.settings.default_timezone, now)
            used = await self._usage(policy, start)
            level = self._alert_level(policy, used)
            if level is None:
                continue
            alert = await self._create_alert(
                policy=policy,
                level=level,
                used=used,
                period_key=self._period_key(policy, now, zone),
                period_start=start,
            )
            if alert is not None:
                created.append(alert)
        return created

    async def list_alerts(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        level: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        safe_page = max(1, page)
        safe_size = min(max(1, page_size), 200)
        conditions: list[Any] = []
        if level:
            if level not in ALERT_LEVEL_LABELS:
                raise AppError(ErrorCode.VALIDATION_ERROR, "告警级别无效。", status_code=400)
            conditions.append(BudgetAlert.level == level)
        if scope_type:
            if scope_type not in SUPPORTED_SCOPES:
                raise AppError(ErrorCode.VALIDATION_ERROR, "告警作用域无效。", status_code=400)
            conditions.append(BudgetAlert.scope_type == scope_type)
        if scope_id:
            conditions.append(BudgetAlert.scope_id == scope_id)
        if since is not None:
            conditions.append(BudgetAlert.created_at >= ensure_utc(since))
        async with self.database.session() as session:
            total = await session.scalar(select(func.count(BudgetAlert.id)).where(*conditions))
            records = list(
                (
                    await session.execute(
                        select(BudgetAlert)
                        .where(*conditions)
                        .order_by(BudgetAlert.created_at.desc())
                        .offset((safe_page - 1) * safe_size)
                        .limit(safe_size)
                    )
                ).scalars()
            )
            account_ids = {item.scope_id for item in records if item.scope_type == "account" and item.scope_id}
            group_ids = {item.scope_id for item in records if item.scope_type == "group" and item.scope_id}
            provider_ids = {item.scope_id for item in records if item.scope_type == "provider" and item.scope_id}
            accounts = (
                {
                    item.id: item
                    for item in (await session.execute(select(Account).where(Account.id.in_(account_ids)))).scalars()
                }
                if account_ids
                else {}
            )
            groups = (
                {
                    item.id: item
                    for item in (await session.execute(select(Group).where(Group.id.in_(group_ids)))).scalars()
                }
                if group_ids
                else {}
            )
            providers = (
                {
                    item.id: item
                    for item in (
                        await session.execute(select(LLMProvider).where(LLMProvider.id.in_(provider_ids)))
                    ).scalars()
                }
                if provider_ids
                else {}
            )
        items: list[dict[str, Any]] = []
        for record in records:
            if record.scope_type == "global":
                scope_name = "全局"
            elif record.scope_type == "account":
                account = accounts.get(record.scope_id)
                scope_name = account.display_name if account is not None else "已删除或未知账号"
            elif record.scope_type == "group":
                group = groups.get(record.scope_id)
                scope_name = (group.name or group.platform_group_id) if group is not None else "已删除或未知群"
            elif record.scope_type == "feature":
                scope_name = feature_label(record.scope_id)
            else:
                provider = providers.get(record.scope_id)
                scope_name = provider.name if provider is not None else "已删除或未知 Provider"
            items.append(
                {
                    "id": record.id,
                    "policy_id": record.policy_id,
                    "scope_type": record.scope_type,
                    "scope_id": record.scope_id,
                    "scope_name": scope_name,
                    "window": record.window,
                    "metric": record.metric,
                    "level": record.level,
                    "period_key": record.period_key,
                    "period_start": iso_utc(record.period_start),
                    "used": round(record.used_value, 8),
                    "limit": record.limit_value,
                    "warn_threshold": record.warn_threshold,
                    "usage_ratio": record.usage_ratio,
                    "message": record.message,
                    "created_at": iso_utc(record.created_at),
                }
            )
        return {
            "items": items,
            "total": int(total or 0),
            "page": safe_page,
            "page_size": safe_size,
            "note": ALERT_NOTE,
        }

    async def record(
        self,
        *,
        provider_id: str | None,
        group_id: str | None,
        feature: str,
        account_id: str | None = None,
        requests: float = 1.0,
        tokens: float = 0.0,
        estimated_cost: float | None = None,
    ) -> None:
        now = utcnow()
        day_start = start_of_day_utc(now, self.settings.default_timezone)
        normalized_feature = normalize_feature_key(feature) or "chat"
        scopes: list[tuple[str, str]] = [("global", "")]
        if account_id:
            scopes.append(("account", account_id))
        if group_id:
            scopes.append(("group", group_id))
        if provider_id:
            scopes.append(("provider", provider_id))
        # 功能作用域只对固定功能键生效；未知 purpose 仍记录在用量事件里，
        # 但不会被任何功能预算匹配。
        if normalized_feature in FEATURE_KEYS:
            scopes.append(("feature", normalized_feature))
        entries: list[tuple[str, str, str, float, float | None]] = []
        for scope_type, scope_id in scopes:
            entries.append((scope_type, scope_id, "requests", requests, None))
            if tokens > 0:
                entries.append((scope_type, scope_id, "tokens", tokens, None))
            if estimated_cost is not None and estimated_cost > 0:
                entries.append((scope_type, scope_id, "cost", estimated_cost, estimated_cost))
        async with self.database.session() as session:
            for scope_type, scope_id, metric, amount, cost in entries:
                session.add(
                    UsageEvent(
                        scope_type=scope_type,
                        scope_id=scope_id,
                        provider_id=provider_id,
                        feature=normalized_feature,
                        metric=metric,
                        amount=amount,
                        estimated_cost=cost,
                        window_start=day_start,
                    )
                )
            await session.commit()
        # 告警是旁路能力：写入失败不能回滚已经发生的模型调用用量。
        try:
            await self._evaluate_alerts(
                group_id=group_id,
                provider_id=provider_id,
                account_id=account_id,
                feature=normalized_feature,
            )
        except Exception:
            logger.exception("预算告警评估失败", extra={"event": "budget.alert.failed"})

    async def list_policies(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            policies = list((await session.execute(select(BudgetPolicy).order_by(BudgetPolicy.scope_type))).scalars())
        return [await self._policy_snapshot(policy) for policy in policies]

    async def get_policy(self, policy_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            policy = await session.get(BudgetPolicy, policy_id)
        if policy is None:
            raise AppError(ErrorCode.NOT_FOUND, "预算策略不存在。", status_code=404)
        return await self._policy_snapshot(policy)

    def _public_policy(self, policy: BudgetPolicy) -> dict[str, Any]:
        return {
            "id": policy.id,
            "scope_type": policy.scope_type,
            "scope_id": policy.scope_id,
            "window": policy.window,
            "metric": policy.metric,
            "limit_value": policy.limit_value,
            "warn_threshold": policy.warn_threshold,
            "action": policy.action,
            "enabled": policy.enabled,
        }

    async def _policy_snapshot(self, policy: BudgetPolicy) -> dict[str, Any]:
        start = window_start(policy.window, self.settings.default_timezone)
        used = await self._usage(policy, start)
        limit = float(policy.limit_value)
        ratio = used / limit if limit > 0 else 0.0
        # 使用四舍五入后的比率判断告警，避免 0.08 / 0.1 这类浮点误差漏报。
        rounded_ratio = round(ratio, 6)
        if not policy.enabled:
            state = "disabled"
        elif limit > 0 and used >= limit:
            state = "exceeded"
        elif policy.warn_threshold > 0 and rounded_ratio >= policy.warn_threshold:
            state = "warning"
        else:
            state = "ok"
        data = {
            **self._public_policy(policy),
            "used": round(used, 8),
            "remaining": round(max(limit - used, 0.0), 8),
            "usage_ratio": round(ratio, 6),
            "state": state,
            "period_start": iso_utc(start) if start is not None else None,
        }
        if policy.metric == "cost":
            data.update(await self._policy_cost_status(policy, start))
        else:
            data.update(
                {
                    "cost_status": None,
                    "unpriced_success_requests": 0,
                }
            )
        return data

    async def _policy_cost_status(self, policy: BudgetPolicy, start: datetime | None) -> dict[str, Any]:
        success = LLMUsage.status == "success"
        known_cost = or_(LLMUsage.estimated_cost.is_not(None), LLMUsage.provider_type == "mock")
        mock_success = and_(success, LLMUsage.provider_type == "mock")
        query = select(
            func.coalesce(func.sum(case((success, 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(success, known_cost), 1), else_=0)), 0),
            func.coalesce(func.sum(case((mock_success, 1), else_=0)), 0),
        )
        if start is not None:
            query = query.where(LLMUsage.created_at >= start)
        if policy.scope_type == "account":
            query = query.where(LLMUsage.account_id == policy.scope_id)
        elif policy.scope_type == "group":
            query = query.where(LLMUsage.group_id == policy.scope_id)
        elif policy.scope_type == "provider":
            query = query.where(LLMUsage.provider_id == policy.scope_id)
        elif policy.scope_type == "feature":
            if policy.scope_id == "chat":
                query = query.where(LLMUsage.purpose.in_(("chat", "reply")))
            else:
                query = query.where(LLMUsage.purpose == policy.scope_id)
        async with self.database.session() as session:
            row = (await session.execute(query)).one()
        successes, priced, mock_successes = (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
        return {
            "cost_status": cost_status(successes, priced, mock_successes),
            "unpriced_success_requests": max(0, successes - priced),
        }

    async def _validate_scope_target(self, scope_type: str, scope_id: str) -> None:
        if scope_type == "global":
            return
        if scope_type == "feature":
            if scope_id not in FEATURE_KEYS:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"功能预算必须使用固定功能键：{', '.join(sorted(FEATURE_KEYS))}。",
                    status_code=400,
                )
            return
        async with self.database.session() as session:
            if scope_type == "account":
                exists = await session.get(Account, scope_id) is not None
            elif scope_type == "group":
                exists = await session.get(Group, scope_id) is not None
            else:
                exists = await session.get(LLMProvider, scope_id) is not None
        if not exists:
            label = {"account": "账号", "group": "群"}.get(scope_type, "模型 Provider")
            raise AppError(ErrorCode.VALIDATION_ERROR, f"预算绑定的{label}不存在。", status_code=400)

    async def upsert_policy(self, payload: dict[str, Any], policy_id: str | None = None) -> dict[str, Any]:
        scope_type = str(payload.get("scope_type", "global"))
        window = str(payload.get("window", "day"))
        metric = str(payload.get("metric", "requests"))
        scope_id = str(payload.get("scope_id") or "")
        if scope_type not in SUPPORTED_SCOPES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "预算作用域无效。", status_code=400)
        if window not in SUPPORTED_WINDOWS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "预算窗口无效。", status_code=400)
        if metric not in SUPPORTED_METRICS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "预算指标无效。", status_code=400)
        if scope_type != "global" and not scope_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "账号、群、Provider 或功能预算必须指定作用域 ID。",
                status_code=400,
            )
        limit_value = float(payload.get("limit_value") or 0)
        if limit_value < 0:
            raise AppError(ErrorCode.VALIDATION_ERROR, "预算上限不能为负数。", status_code=400)
        await self._validate_scope_target(scope_type, scope_id)
        async with self.database.session() as session:
            policy: BudgetPolicy | None = None
            if policy_id:
                policy = await session.get(BudgetPolicy, policy_id)
                if policy is None:
                    raise AppError(ErrorCode.NOT_FOUND, "预算策略不存在。", status_code=404)
            else:
                policy = await session.scalar(
                    select(BudgetPolicy).where(
                        BudgetPolicy.scope_type == scope_type,
                        BudgetPolicy.scope_id == scope_id,
                        BudgetPolicy.window == window,
                        BudgetPolicy.metric == metric,
                    )
                )
            if policy is None:
                policy = BudgetPolicy()
                session.add(policy)
            policy.scope_type = scope_type
            policy.scope_id = scope_id
            policy.window = window
            policy.metric = metric
            policy.limit_value = limit_value
            policy.warn_threshold = min(max(float(payload.get("warn_threshold", 0.8)), 0.0), 1.0)
            policy.action = str(payload.get("action", "pause"))
            policy.enabled = bool(payload.get("enabled", True))
            await session.commit()
            await session.refresh(policy)
        # 新建或调整策略后立即按当前真实用量评估一次，避免必须等到下一次调用才出现告警。
        try:
            await self._evaluate_alerts(
                group_id=scope_id if scope_type == "group" else None,
                provider_id=scope_id if scope_type == "provider" else None,
                account_id=scope_id if scope_type == "account" else None,
                feature=scope_id if scope_type == "feature" else None,
            )
        except Exception:
            logger.exception("预算告警评估失败", extra={"event": "budget.alert.failed"})
        return await self._policy_snapshot(policy)

    async def _usage_snapshot(
        self,
        *,
        since: datetime,
        until: datetime,
        hours: int | None = None,
    ) -> dict[str, Any]:
        async with self.database.session() as session:
            provider_rows = (await session.execute(_aggregate_query(LLMUsage.provider_id, since, until))).all()
            group_rows = (await session.execute(_aggregate_query(LLMUsage.group_id, since, until))).all()
            providers = list(
                (
                    await session.execute(
                        select(LLMProvider).order_by(LLMProvider.is_default.desc(), LLMProvider.created_at)
                    )
                ).scalars()
            )
            groups = list((await session.execute(select(Group).order_by(Group.created_at))).scalars())

        provider_buckets: dict[str | None, dict[str, Any]] = {}
        for provider_record in providers:
            pricing = provider_pricing_state(provider_record)
            provider_buckets[provider_record.id] = {
                **_empty_bucket(),
                "provider_id": provider_record.id,
                "provider_name": provider_record.name,
                "provider_type": provider_record.provider_type,
                "model": provider_record.model,
                "is_mock": provider_record.provider_type == "mock",
                "cost_tracking": pricing,
            }
        for row in provider_rows:
            bucket = provider_buckets.get(row.bucket)
            if bucket is None:
                bucket = {
                    **_empty_bucket(),
                    "provider_id": row.bucket,
                    "provider_name": "已删除或未知 Provider" if row.bucket else "未记录 Provider",
                    "provider_type": "unknown",
                    "model": None,
                    "is_mock": False,
                    "cost_tracking": COST_STATUS_UNCONFIGURED,
                }
                provider_buckets[row.bucket] = bucket
            bucket.update(_bucket_values(row))

        group_buckets: dict[str | None, dict[str, Any]] = {}
        for group_record in groups:
            group_buckets[group_record.id] = {
                **_empty_bucket(),
                "group_id": group_record.id,
                "group_name": group_record.name or group_record.platform_group_id,
            }
        for row in group_rows:
            bucket = group_buckets.get(row.bucket)
            if bucket is None:
                bucket = {
                    **_empty_bucket(),
                    "group_id": row.bucket,
                    "group_name": "未关联群" if row.bucket is None else "已删除群",
                }
                group_buckets[row.bucket] = bucket
            bucket.update(_bucket_values(row))

        by_provider = sorted(
            provider_buckets.values(),
            key=lambda item: (-int(item["requests"]), str(item["provider_name"] or "")),
        )
        by_group = sorted(
            group_buckets.values(),
            key=lambda item: (-int(item["requests"]), str(item["group_name"] or "")),
        )

        total_requests = sum(int(item["requests"]) for item in provider_buckets.values())
        total_successes = sum(int(item["successful_requests"]) for item in provider_buckets.values())
        total_priced = sum(int(item["priced_success_requests"]) for item in provider_buckets.values())
        total_mock_successes = 0
        total_cost = 0.0
        for row in provider_rows:
            total_mock_successes += int(row.mock_successes or 0)
            total_cost += float(row.cost or 0.0)

        return {
            "hours": hours,
            "window_start": iso_utc(since),
            "window_end": iso_utc(until),
            "requests": total_requests,
            "successful_requests": total_successes,
            "failed_requests": max(0, total_requests - total_successes),
            "tokens": sum(int(item["tokens"]) for item in provider_buckets.values()),
            "cost": _cost_value(total_cost, total_priced),
            "currency": "USD",
            "priced_success_requests": total_priced,
            "unpriced_success_requests": max(0, total_successes - total_priced),
            "cost_status": cost_status(total_successes, total_priced, total_mock_successes),
            "cost_note": COST_NOTE,
            "by_provider": by_provider,
            "by_group": by_group,
        }

    async def usage_summary(self, hours: int = 24) -> dict[str, Any]:
        safe_hours = max(1, min(hours, 24 * 31))
        until = utcnow()
        since = until - timedelta(hours=safe_hours)
        return await self._usage_snapshot(since=since, until=until, hours=safe_hours)

    async def usage_since(self, since: datetime) -> dict[str, Any]:
        until = utcnow()
        return await self._usage_snapshot(since=since, until=until, hours=None)

    async def usage_trends(
        self,
        *,
        bucket: str = "hour",
        periods: int = 24,
        group_id: str | None = None,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """按配置时区的小时或自然日聚合真实 llm_usage 记录。

        缺失 Token/单价的成功调用仍会计入请求数，但费用保持 null；
        不把未知成本补成 0。
        """
        if bucket not in TREND_BUCKETS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "趋势粒度必须为 hour 或 day。", status_code=400)
        max_periods = 24 * 31 if bucket == "hour" else 365
        if periods < 1 or periods > max_periods:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"趋势周期数必须在 1 到 {max_periods} 之间。",
                status_code=400,
            )
        zone = get_zone(self.settings.default_timezone)
        until = utcnow()
        local_now = until.astimezone(zone)
        if bucket == "hour":
            last_start = local_now.replace(minute=0, second=0, microsecond=0)
            starts = [last_start - timedelta(hours=offset) for offset in range(periods - 1, -1, -1)]
            label_format = "%Y-%m-%d %H:00"
            step = timedelta(hours=1)
        else:
            last_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            starts = [last_start - timedelta(days=offset) for offset in range(periods - 1, -1, -1)]
            label_format = "%Y-%m-%d"
            step = timedelta(days=1)

        keyed: dict[datetime, dict[str, Any]] = {}
        ordered: list[tuple[datetime, dict[str, Any]]] = []
        for start in starts:
            accumulator = _accumulator()
            keyed[start] = accumulator
            ordered.append((start, accumulator))

        since = starts[0].astimezone(UTC)
        conditions: list[Any] = [LLMUsage.created_at >= since, LLMUsage.created_at <= until]
        if group_id:
            conditions.append(LLMUsage.group_id == group_id)
        if provider_id:
            conditions.append(LLMUsage.provider_id == provider_id)
        query = select(
            LLMUsage.created_at,
            LLMUsage.status,
            LLMUsage.total_tokens,
            LLMUsage.estimated_cost,
            LLMUsage.provider_type,
        ).where(*conditions)
        async with self.database.session() as session:
            rows = (await session.execute(query)).all()

        total_accumulator = _accumulator()
        for row in rows:
            created_at = ensure_utc(row.created_at)
            if created_at is None:
                continue
            local = created_at.astimezone(zone)
            if bucket == "hour":
                key = local.replace(minute=0, second=0, microsecond=0)
            else:
                key = local.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket_accumulator = keyed.get(key)
            if bucket_accumulator is None:
                continue
            _add_to_accumulator(
                bucket_accumulator,
                status=row.status,
                total_tokens=row.total_tokens,
                estimated_cost=row.estimated_cost,
                provider_type=row.provider_type,
            )
            _add_to_accumulator(
                total_accumulator,
                status=row.status,
                total_tokens=row.total_tokens,
                estimated_cost=row.estimated_cost,
                provider_type=row.provider_type,
            )

        items: list[dict[str, Any]] = []
        for start, accumulator in ordered:
            end = start + step
            items.append(
                {
                    "bucket_start": iso_utc(start.astimezone(UTC)),
                    "bucket_end": iso_utc(end.astimezone(UTC)),
                    "bucket_label": start.strftime(label_format),
                    **_finalize_accumulator(accumulator),
                }
            )

        totals = _finalize_accumulator(total_accumulator)
        return {
            "bucket": bucket,
            "periods": periods,
            "timezone": self.settings.default_timezone,
            "window_start": iso_utc(since),
            "window_end": iso_utc(until),
            "items": items,
            **totals,
            "cost_note": COST_NOTE,
        }
