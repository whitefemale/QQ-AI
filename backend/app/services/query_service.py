"""消息、发送队列、用量查询与仪表盘聚合。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.time import iso_utc, start_of_day_utc, utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.governance import UsageEvent
from app.models.group import Group
from app.models.message import Message, OutboxMessage
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.events import EventBus
from app.services.provider_service import ProviderService


def _page_bounds(page: int, page_size: int) -> tuple[int, int]:
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 200)
    return safe_size, (safe_page - 1) * safe_size


class MessageQueryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_messages(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        account_id: str | None = None,
        group_id: str | None = None,
        conversation_id: str | None = None,
        direction: str | None = None,
        status: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        size, offset = _page_bounds(page, page_size)
        conditions: list[Any] = []
        if account_id:
            conditions.append(Message.account_id == account_id)
        if group_id:
            conditions.append(Message.group_id == group_id)
        if conversation_id:
            conditions.append(Message.conversation_id == conversation_id)
        if direction:
            conditions.append(Message.direction == direction)
        if status:
            conditions.append(Message.processing_status == status)
        if search:
            like = f"%{search.strip()[:100]}%"
            conditions.append(
                or_(
                    Message.content_text.ilike(like),
                    Message.sender_name.ilike(like),
                    Message.sender_id.ilike(like),
                )
            )
        if since:
            conditions.append(Message.event_timestamp >= since)
        if until:
            conditions.append(Message.event_timestamp <= until)
        async with self.database.session() as session:
            total = await session.scalar(select(func.count(Message.id)).where(*conditions))
            records = list(
                (
                    await session.execute(
                        select(Message)
                        .where(*conditions)
                        .order_by(Message.event_timestamp.desc())
                        .offset(offset)
                        .limit(size)
                    )
                ).scalars()
            )
            group_names = {item.id: item.name for item in (await session.execute(select(Group))).scalars()}
            account_names = {item.id: item.display_name for item in (await session.execute(select(Account))).scalars()}
        items = [
            {
                "id": record.id,
                "platform_message_id": record.platform_message_id,
                "account_id": record.account_id,
                "account_name": account_names.get(record.account_id),
                "group_id": record.group_id,
                "group_name": group_names.get(record.group_id or ""),
                "conversation_id": record.conversation_id,
                "conversation_type": record.conversation_type,
                "sender_id": record.sender_id,
                "sender_name": record.sender_name,
                "is_self": record.is_self,
                "direction": record.direction,
                "content_text": record.content_text[:4000],
                "segments": record.segments_json,
                "reply_to_message_id": record.reply_to_message_id,
                "event_timestamp": iso_utc(record.event_timestamp),
                "processing_status": record.processing_status,
                "trigger_reason": record.trigger_reason,
                "error_code": record.error_code,
                "error_message": record.error_message,
                "model_latency_ms": record.model_latency_ms,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "created_at": iso_utc(record.created_at),
            }
            for record in records
        ]
        return {
            "items": items,
            "total": int(total or 0),
            "page": max(1, page),
            "page_size": size,
        }

    async def list_outbox(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        size, offset = _page_bounds(page, page_size)
        conditions: list[Any] = []
        if status:
            conditions.append(OutboxMessage.status == status)
        if group_id:
            conditions.append(OutboxMessage.group_id == group_id)
        async with self.database.session() as session:
            total = await session.scalar(select(func.count(OutboxMessage.id)).where(*conditions))
            records = list(
                (
                    await session.execute(
                        select(OutboxMessage)
                        .where(*conditions)
                        .order_by(OutboxMessage.created_at.desc())
                        .offset(offset)
                        .limit(size)
                    )
                ).scalars()
            )
        return {
            "items": [
                {
                    "id": record.id,
                    "account_id": record.account_id,
                    "group_id": record.group_id,
                    "conversation_id": record.conversation_id,
                    "conversation_type": record.conversation_type,
                    "content": record.content,
                    "status": record.status,
                    "attempts": record.attempts,
                    "max_attempts": record.max_attempts,
                    "next_attempt_at": iso_utc(record.next_attempt_at),
                    "last_error_code": record.last_error_code,
                    "last_error_message": record.last_error_message,
                    "sent_platform_message_id": record.sent_platform_message_id,
                    "sent_at": iso_utc(record.sent_at),
                    "created_at": iso_utc(record.created_at),
                }
                for record in records
            ],
            "total": int(total or 0),
            "page": max(1, page),
            "page_size": size,
        }

    async def export_usage(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        group_id: str | None = None,
        provider_id: str | None = None,
        purpose: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回真实 llm_usage 元数据，供 CSV 导出；不包含消息正文或凭证。"""
        conditions: list[Any] = []
        if since is not None:
            conditions.append(LLMUsage.created_at >= since)
        if until is not None:
            conditions.append(LLMUsage.created_at <= until)
        if group_id:
            conditions.append(LLMUsage.group_id == group_id)
        if provider_id:
            conditions.append(LLMUsage.provider_id == provider_id)
        if purpose:
            conditions.append(LLMUsage.purpose == purpose)
        if status:
            conditions.append(LLMUsage.status == status)
        async with self.database.session() as session:
            records = list(
                (
                    await session.execute(select(LLMUsage).where(*conditions).order_by(LLMUsage.created_at.asc()))
                ).scalars()
            )
        return [
            {
                "created_at_utc": iso_utc(record.created_at),
                "provider_id": record.provider_id,
                "provider_type": record.provider_type,
                "model": record.model,
                "purpose": record.purpose,
                "group_id": record.group_id,
                "conversation_id": record.conversation_id,
                "message_id": record.message_id,
                "status": record.status,
                "error_code": record.error_code,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "latency_ms": record.latency_ms,
                "estimated_cost": record.estimated_cost,
                "currency": record.currency,
                "request_id": record.request_id,
            }
            for record in records
        ]

    async def list_usage(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        provider_id: str | None = None,
        purpose: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        size, offset = _page_bounds(page, page_size)
        conditions: list[Any] = []
        if provider_id:
            conditions.append(LLMUsage.provider_id == provider_id)
        if purpose:
            conditions.append(LLMUsage.purpose == purpose)
        if status:
            conditions.append(LLMUsage.status == status)
        async with self.database.session() as session:
            total = await session.scalar(select(func.count(LLMUsage.id)).where(*conditions))
            records = list(
                (
                    await session.execute(
                        select(LLMUsage)
                        .where(*conditions)
                        .order_by(LLMUsage.created_at.desc())
                        .offset(offset)
                        .limit(size)
                    )
                ).scalars()
            )
        return {
            "items": [
                {
                    "id": record.id,
                    "provider_id": record.provider_id,
                    "provider_type": record.provider_type,
                    "model": record.model,
                    "purpose": record.purpose,
                    "message_id": record.message_id,
                    "conversation_id": record.conversation_id,
                    "group_id": record.group_id,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "total_tokens": record.total_tokens,
                    "latency_ms": record.latency_ms,
                    "estimated_cost": record.estimated_cost,
                    "currency": record.currency,
                    "status": record.status,
                    "error_code": record.error_code,
                    "created_at": iso_utc(record.created_at),
                }
                for record in records
            ],
            "total": int(total or 0),
            "page": max(1, page),
            "page_size": size,
        }


class DashboardService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        events: EventBus,
        provider_service: ProviderService,
        budget_service: BudgetService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.events = events
        self.provider_service = provider_service
        self.budget_service = budget_service

    async def build(self) -> dict[str, Any]:
        today = start_of_day_utc(utcnow(), self.settings.default_timezone)
        async with self.database.session() as session:
            accounts_total = await session.scalar(select(func.count(Account.id)))
            accounts_online = await session.scalar(select(func.count(Account.id)).where(Account.status == "online"))
            groups_total = await session.scalar(select(func.count(Group.id)))
            groups_active = await session.scalar(
                select(func.count(Group.id)).where(Group.enabled.is_(True), Group.paused.is_(False))
            )
            inbound_today = await session.scalar(
                select(func.count(Message.id)).where(
                    Message.direction == "inbound",
                    Message.event_timestamp >= today,
                )
            )
            outbound_today = await session.scalar(
                select(func.count(Message.id)).where(
                    Message.direction == "outbound",
                    Message.event_timestamp >= today,
                )
            )
            errors_today = await session.scalar(
                select(func.count(Message.id)).where(
                    Message.error_code.is_not(None),
                    Message.event_timestamp >= today,
                )
            )
            outbox_rows = (
                await session.execute(
                    select(OutboxMessage.status, func.count(OutboxMessage.id)).group_by(OutboxMessage.status)
                )
            ).all()
            provider_records = list(
                (
                    await session.execute(
                        select(LLMProvider).order_by(LLMProvider.is_default.desc(), LLMProvider.created_at)
                    )
                ).scalars()
            )
            recent_messages = list(
                (await session.execute(select(Message).order_by(Message.event_timestamp.desc()).limit(8))).scalars()
            )
            group_names = {item.id: item.name for item in (await session.execute(select(Group))).scalars()}
        default_provider = next((item for item in provider_records if item.is_default), None)
        capabilities = await self.provider_service.capability_overview()
        budget = await self.budget_service.usage_summary(hours=24)
        today_usage = await self.budget_service.usage_since(today)
        return {
            "app": {
                "name": self.settings.app_name,
                "version": self.settings.app_version,
                "env": self.settings.app_env,
            },
            "accounts": {
                "total": int(accounts_total or 0),
                "online": int(accounts_online or 0),
            },
            "groups": {
                "total": int(groups_total or 0),
                "active": int(groups_active or 0),
            },
            "messages": {
                "inbound_today": int(inbound_today or 0),
                "outbound_today": int(outbound_today or 0),
                "errors_today": int(errors_today or 0),
            },
            "outbox": {str(status): int(count) for status, count in outbox_rows},
            "providers": {
                "total": len(provider_records),
                "enabled": sum(1 for item in provider_records if item.enabled),
                "default": None
                if default_provider is None
                else {
                    "id": default_provider.id,
                    "name": default_provider.name,
                    "model": default_provider.model,
                    "provider_type": default_provider.provider_type,
                    "is_mock": default_provider.provider_type == "mock",
                    "status": default_provider.status,
                },
            },
            "usage_today": {
                "requests": today_usage["requests"],
                "successful_requests": today_usage["successful_requests"],
                "failed_requests": today_usage["failed_requests"],
                "tokens": today_usage["tokens"],
                "cost": today_usage["cost"],
                "currency": today_usage["currency"],
                "cost_status": today_usage["cost_status"],
                "cost_note": today_usage["cost_note"],
                "priced_success_requests": today_usage["priced_success_requests"],
                "unpriced_success_requests": today_usage["unpriced_success_requests"],
                "by_provider": today_usage["by_provider"],
                "by_group": today_usage["by_group"],
                "last_24h": budget,
            },
            "capabilities": capabilities,
            "recent_events": self.events.recent(limit=20),
            "recent_messages": [
                {
                    "id": record.id,
                    "direction": record.direction,
                    "sender_name": record.sender_name,
                    "group_id": record.group_id,
                    "group_name": group_names.get(record.group_id or ""),
                    "preview": record.content_text[:160],
                    "status": record.processing_status,
                    "at": iso_utc(record.event_timestamp),
                }
                for record in recent_messages
            ],
            "usage_events": await self._usage_events_today(today),
        }

    async def _usage_events_today(self, today: datetime) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(UsageEvent.metric, func.coalesce(func.sum(UsageEvent.amount), 0.0))
                    .where(UsageEvent.created_at >= today)
                    .group_by(UsageEvent.metric)
                )
            ).all()
        return [{"metric": metric, "amount": float(amount or 0)} for metric, amount in rows]
