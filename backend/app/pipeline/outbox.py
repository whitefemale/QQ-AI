"""发送队列：幂等、状态机、未知状态不重发、有限重试与连续失败自动暂停。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.qq.base import BaseQQAdapter
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group
from app.models.message import OutboxMessage
from app.pipeline.events import EventBus
from app.services.audit import write_audit
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)

AdapterResolver = Callable[[str, str | None], Awaitable[BaseQQAdapter | None] | BaseQQAdapter | None]


class OutboxService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        message_service: MessageService,
        events: EventBus,
    ) -> None:
        self.database = database
        self.settings = settings
        self.message_service = message_service
        self.events = events
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, outbox_id: str) -> asyncio.Lock:
        return self._locks.setdefault(outbox_id, asyncio.Lock())

    async def enqueue(
        self,
        *,
        account_id: str,
        group_id: str | None,
        conversation_id: str,
        conversation_type: str,
        content: str,
        idempotency_key: str,
        reply_to_message_id: str | None = None,
        adapter_instance_id: str | None = None,
    ) -> OutboxMessage:
        async with self.database.session() as session:
            existing = await session.scalar(
                select(OutboxMessage).where(OutboxMessage.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing
            record = OutboxMessage(
                account_id=account_id,
                group_id=group_id,
                adapter_instance_id=adapter_instance_id,
                conversation_id=conversation_id,
                conversation_type=conversation_type,
                reply_to_message_id=reply_to_message_id,
                content=content,
                idempotency_key=idempotency_key,
                status="pending",
                attempts=0,
                max_attempts=max(1, self.settings.outbox_max_attempts),
                next_attempt_at=utcnow(),
            )
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(OutboxMessage).where(OutboxMessage.idempotency_key == idempotency_key)
                )
                if existing is None:
                    raise
                return existing
            await session.refresh(record)
            return record

    async def get(self, outbox_id: str) -> OutboxMessage | None:
        async with self.database.session() as session:
            return await session.get(OutboxMessage, outbox_id)

    async def send(self, outbox_id: str, adapter: BaseQQAdapter | None) -> OutboxMessage:
        async with self._lock(outbox_id):
            async with self.database.session() as session:
                record = await session.get(OutboxMessage, outbox_id)
                if record is None:
                    raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
                if record.status != "pending":
                    return record
                record.status = "sending"
                record.attempts += 1
                await session.commit()
                await session.refresh(record)

            if adapter is None:
                return await self._fail(
                    record.id,
                    ErrorCode.SEND_FAILED,
                    "账号当前没有可用连接，发送稍后重试。",
                    retryable=True,
                )
            try:
                sent = await adapter.send_text(
                    record.conversation_id,
                    record.content,
                    conversation_type=record.conversation_type,
                    reply_to_message_id=record.reply_to_message_id,
                )
            except AppError as exc:
                if exc.code == ErrorCode.SEND_STATUS_UNKNOWN:
                    return await self._mark_unknown(record.id, exc)
                return await self._fail(record.id, exc.code, exc.message, retryable=exc.retryable)
            except Exception as exc:  # 未知异常：发送状态未知，保险起见不重发
                logger.exception("发送消息时发生未知异常")
                return await self._mark_unknown(
                    record.id,
                    AppError(
                        ErrorCode.SEND_STATUS_UNKNOWN,
                        "发送时发生异常，发送状态未知，已停止重发以避免重复。",
                        details={"reason": type(exc).__name__},
                    ),
                )

            async with self.database.session() as session:
                current = await session.get(OutboxMessage, record.id)
                if current is None:
                    raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
                current.status = "sent"
                current.sent_message_id = sent.platform_message_id
                current.sent_platform_message_id = sent.platform_message_id
                current.sent_at = utcnow()
                current.last_error_code = None
                current.last_error_message = None
                current.next_attempt_at = None
                await session.commit()
                await session.refresh(current)
                account = await session.get(Account, current.account_id)
                sender_id = account.self_platform_user_id if account is not None else "self"
                sender_name = "AI 群友"

            await self.message_service.record_outbound(
                account_id=record.account_id,
                group_id=record.group_id,
                conversation_id=record.conversation_id,
                conversation_type=record.conversation_type,
                content=record.content,
                platform_message_id=sent.platform_message_id,
                sender_id=sender_id or "self",
                sender_name=sender_name,
                reply_to_message_id=record.reply_to_message_id,
            )
            self.events.publish(
                "outbox.sent",
                {
                    "outbox_id": record.id,
                    "account_id": record.account_id,
                    "group_id": record.group_id,
                    "conversation_id": record.conversation_id,
                    "platform_message_id": sent.platform_message_id,
                    "preview": record.content[:80],
                },
            )
            return current

    async def _mark_unknown(self, outbox_id: str, exc: AppError) -> OutboxMessage:
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            record.status = "unknown"
            record.last_error_code = ErrorCode.SEND_STATUS_UNKNOWN
            record.last_error_message = exc.message
            record.next_attempt_at = None
            await session.commit()
            await session.refresh(record)
        await self._maybe_auto_pause(record)
        self.events.publish(
            "outbox.unknown",
            {
                "outbox_id": record.id,
                "group_id": record.group_id,
                "message": "发送状态未知，已停止自动重发，请人工确认后处理。",
            },
        )
        return record

    async def _fail(self, outbox_id: str, code: str, message: str, *, retryable: bool) -> OutboxMessage:
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            record.last_error_code = code
            record.last_error_message = message
            if retryable and record.attempts < record.max_attempts:
                record.status = "pending"
                delay = min(2**record.attempts, 60)
                record.next_attempt_at = utcnow() + timedelta(seconds=delay)
            else:
                record.status = "failed"
                record.next_attempt_at = None
            await session.commit()
            await session.refresh(record)
        if record.status == "failed":
            await self._maybe_auto_pause(record)
        self.events.publish(
            "outbox.failed",
            {
                "outbox_id": record.id,
                "group_id": record.group_id,
                "status": record.status,
                "error_code": code,
                "message": message,
                "attempts": record.attempts,
            },
        )
        return record

    async def _maybe_auto_pause(self, record: OutboxMessage) -> None:
        if record.group_id is None:
            return
        threshold = max(1, self.settings.outbox_failure_pause_threshold)
        async with self.database.session() as session:
            recent = list(
                (
                    await session.execute(
                        select(OutboxMessage)
                        .where(OutboxMessage.group_id == record.group_id)
                        .order_by(OutboxMessage.created_at.desc())
                        .limit(50)
                    )
                ).scalars()
            )
        consecutive = 0
        for item in recent:
            if item.status in {"failed", "unknown"}:
                consecutive += 1
            elif item.status == "sent":
                break
            else:
                continue
        if consecutive < threshold:
            return
        async with self.database.session() as session:
            group = await session.get(Group, record.group_id)
            if group is None or group.paused:
                return
            group.paused = True
            await session.commit()
            group_name = group.name or group.platform_group_id
        await write_audit(
            self.database,
            action="group.auto_pause",
            target_type="group",
            target_id=record.group_id,
            details={"reason": "发送连续失败", "consecutive_failures": consecutive},
            actor="system",
        )
        self.events.publish(
            "outbox.auto_paused",
            {
                "group_id": record.group_id,
                "group_name": group_name,
                "consecutive_failures": consecutive,
                "message": "发送连续失败，已自动暂停该群，请检查连接器后手动恢复。",
            },
        )

    async def send_due(self, resolver: AdapterResolver, limit: int = 10) -> int:
        now = utcnow()
        async with self.database.session() as session:
            records = list(
                (
                    await session.execute(
                        select(OutboxMessage)
                        .where(
                            OutboxMessage.status == "pending",
                            (OutboxMessage.next_attempt_at.is_(None)) | (OutboxMessage.next_attempt_at <= now),
                        )
                        .order_by(OutboxMessage.created_at)
                        .limit(max(1, min(limit, 100)))
                    )
                ).scalars()
            )
        sent = 0
        for record in records:
            resolved = resolver(record.account_id, record.adapter_instance_id)
            if inspect.isawaitable(resolved):
                adapter = await cast(Awaitable[BaseQQAdapter | None], resolved)
            else:
                adapter = cast(BaseQQAdapter | None, resolved)
            result = await self.send(record.id, adapter)
            if result.status == "sent":
                sent += 1
        return sent
