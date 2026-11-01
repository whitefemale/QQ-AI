"""发送队列：幂等、状态机、未知状态不重发、有限重试与连续失败自动暂停。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, NoReturn, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.adapters.qq.base import BaseQQAdapter
from app.core.config import Settings
from app.core.csv import content_digest
from app.core.errors import AppError, ErrorCode
from app.core.time import start_of_day_utc, utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group, Member
from app.models.message import OutboxMessage
from app.pipeline.events import EventBus
from app.pipeline.output_guard import REASON_EMPTY, REASON_SENSITIVE, REASON_TOO_LONG, inspect_output
from app.pipeline.policy import (
    PolicyEngine,
    RateLimitSnapshot,
    check_rate_limits,
    effective_max_reply_chars,
    quiet_hours_decision,
    rate_limits,
)
from app.services.audit import write_audit
from app.services.message_service import MessageService
from app.services.settings_store import get_global_pause

logger = logging.getLogger(__name__)

AdapterResolver = Callable[[str, str | None], Awaitable[BaseQQAdapter | None] | BaseQQAdapter | None]


class OutboxService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        message_service: MessageService,
        events: EventBus,
        policy: PolicyEngine | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.message_service = message_service
        self.events = events
        self.policy = policy
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
        origin_member_platform_user_id: str | None = None,
        reply_kind: str = "reply",
        status: str = "pending",
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
                origin_member_platform_user_id=origin_member_platform_user_id,
                reply_kind=reply_kind,
                content=content,
                idempotency_key=idempotency_key,
                status=status,
                attempts=0,
                max_attempts=max(1, self.settings.outbox_max_attempts),
                next_attempt_at=utcnow() if status == "pending" else None,
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
            blocked_reason: str | None = None
            async with self.database.session() as session:
                record = await session.get(OutboxMessage, outbox_id)
                if record is None:
                    raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
                if record.status != "pending":
                    return record
                group = await session.get(Group, record.group_id) if record.group_id else None
                max_chars = effective_max_reply_chars(group, self.settings.max_reply_chars)
                inspection = inspect_output(record.content, max_chars, truncate=False)
                if inspection.blocked:
                    blocked_reason = inspection.reason
                else:
                    if inspection.text != record.content:
                        record.content = inspection.text
                    record.status = "sending"
                    record.attempts += 1
                    await session.commit()
                    await session.refresh(record)

            if blocked_reason is not None:
                return await self._fail_output(outbox_id, blocked_reason, max_chars)
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

    async def approve(
        self,
        outbox_id: str,
        *,
        content: str | None = None,
        adapter: BaseQQAdapter | None = None,
        actor: str = "local-admin",
    ) -> OutboxMessage:
        """人工批准待审回复：完整复查后原子切换到 pending，并立即尝试发送一次。"""
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            if record.status != "pending_approval":
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason="not_pending_approval",
                    detail="该消息不在待确认状态，可能已被批准或拒绝。",
                    actor=actor,
                    original=record.content,
                    proposed=record.content,
                )
            group = await session.get(Group, record.group_id) if record.group_id else None
            account = await session.get(Account, record.account_id)
            origin = record.origin_member_platform_user_id
            member = None
            if origin:
                member = await session.scalar(
                    select(Member).where(
                        Member.account_id == record.account_id,
                        Member.platform_user_id == origin,
                    )
                )
            original = record.content
            proposed = original if content is None else str(content)
            group_id = record.group_id
            conversation_id = record.conversation_id
            account_id = record.account_id

        now = utcnow()
        max_chars = effective_max_reply_chars(group, self.settings.max_reply_chars)
        inspection = inspect_output(proposed, max_chars, truncate=False)
        if inspection.blocked:
            detail = {
                REASON_SENSITIVE: "编辑后的内容疑似包含密码、验证码、证件号或密钥，已阻止批准。",
                REASON_EMPTY: "待发送内容为空，已阻止批准。",
                REASON_TOO_LONG: f"内容超过群级字数上限（{max_chars}），已阻止批准。",
            }.get(inspection.reason or "", "输出审查未通过，已阻止批准。")
            await self._approval_conflict(
                outbox_id,
                action="outbox.approve",
                reason=inspection.reason or "output_rejected",
                detail=detail,
                actor=actor,
                original=original,
                proposed=proposed,
            )

        pause = await get_global_pause(self.database)
        if pause.get("paused"):
            await self._approval_conflict(
                outbox_id,
                action="outbox.approve",
                reason="global_paused",
                detail="全局紧急暂停中，不能批准发送。",
                actor=actor,
                original=original,
                proposed=proposed,
            )
        if account is None or not account.enabled:
            await self._approval_conflict(
                outbox_id,
                action="outbox.approve",
                reason="account_disabled",
                detail="账号不存在或已停用，不能批准发送。",
                actor=actor,
                original=original,
                proposed=proposed,
            )
        if group_id is not None:
            if group is None or not group.enabled:
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason="group_disabled",
                    detail="群不存在或 AI 群友功能已关闭，不能批准发送。",
                    actor=actor,
                    original=original,
                    proposed=proposed,
                )
            if group.paused:
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason="group_paused",
                    detail="该群已暂停回复，不能批准发送。",
                    actor=actor,
                    original=original,
                    proposed=proposed,
                )
            quiet = quiet_hours_decision(group, now)
            if quiet is not None:
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason=quiet.reason,
                    detail=quiet.detail or "当前处于安静时段。",
                    actor=actor,
                    original=original,
                    proposed=proposed,
                )
            if member is not None and member.muted_until is not None and member.muted_until > now:
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason="member_muted",
                    detail="触发成员已被静默，不能批准发送。",
                    actor=actor,
                    original=original,
                    proposed=proposed,
                )
            group_hour = await self.message_service.outbound_stats(group.id, now - timedelta(hours=1))
            group_today = await self.message_service.outbound_stats(group.id, start_of_day_utc(now, group.timezone))
            member_hour: dict = {}
            member_today: dict = {}
            if origin:
                member_hour = await self.message_service.outbox_stats_by_origin(
                    account_id, group.id, origin, now - timedelta(hours=1)
                )
                member_today = await self.message_service.outbox_stats_by_origin(
                    account_id, group.id, origin, start_of_day_utc(now, group.timezone)
                )
            snapshot = RateLimitSnapshot(
                last_reply_at=group_hour.get("last_at"),
                replies_last_hour=int(group_hour.get("count") or 0),
                replies_today=int(group_today.get("count") or 0),
                consecutive_replies=(
                    self.policy.current_consecutive(conversation_id) if self.policy is not None else 0
                ),
                member_replies_last_hour=int(member_hour.get("count") or 0),
                member_replies_today=int(member_today.get("count") or 0),
            )
            blocked = check_rate_limits(snapshot, rate_limits(group), now)
            if blocked is not None:
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason=blocked.reason,
                    detail=blocked.detail or "频率限制未通过。",
                    actor=actor,
                    original=original,
                    proposed=proposed,
                )

        async with self.database.session() as session:
            result = await session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == outbox_id, OutboxMessage.status == "pending_approval")
                .values(
                    status="pending",
                    content=inspection.text,
                    next_attempt_at=now,
                    last_error_code=None,
                    last_error_message=None,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                await session.rollback()
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.approve",
                    reason="approval_conflict",
                    detail="该消息已被其他操作处理，请刷新后重试。",
                    actor=actor,
                    original=original,
                    proposed=inspection.text,
                )
            await session.commit()

        await write_audit(
            self.database,
            action="outbox.approve",
            target_type="outbox_message",
            target_id=outbox_id,
            details={
                "result": "approved",
                "content_changed": inspection.text != original,
                "original_chars": len(original),
                "new_chars": len(inspection.text),
                "original_sha256": content_digest(original),
                "new_sha256": content_digest(inspection.text),
                "origin_member_platform_user_id": origin,
            },
            actor=actor,
        )
        if adapter is not None:
            return await self.send(outbox_id, adapter)
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id, populate_existing=True)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            return record

    async def reject(self, outbox_id: str, *, reason: str | None = None, actor: str = "local-admin") -> OutboxMessage:
        """拒绝待审回复；只有 pending_approval 可以拒绝。"""
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            if record.status != "pending_approval":
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.reject",
                    reason="not_pending_approval",
                    detail="该消息不在待确认状态，可能已被批准或拒绝。",
                    actor=actor,
                    original=record.content,
                    proposed=record.content,
                )
            original = record.content
            note = (reason or "").strip()[:200]

        async with self.database.session() as session:
            result = await session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == outbox_id, OutboxMessage.status == "pending_approval")
                .values(
                    status="rejected",
                    next_attempt_at=None,
                    last_error_code="OUTBOX_REJECTED",
                    last_error_message=note or "管理员已拒绝发送。",
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                await session.rollback()
                await self._approval_conflict(
                    outbox_id,
                    action="outbox.reject",
                    reason="reject_conflict",
                    detail="该消息已被其他操作处理，请刷新后重试。",
                    actor=actor,
                    original=original,
                    proposed=original,
                )
            await session.commit()

        await write_audit(
            self.database,
            action="outbox.reject",
            target_type="outbox_message",
            target_id=outbox_id,
            details={"result": "rejected", "reason_present": bool(note), "content_sha256": content_digest(original)},
            actor=actor,
        )
        self.events.publish(
            "outbox.rejected",
            {"outbox_id": outbox_id, "message": "管理员已拒绝该条 AI 回复，不会发送。"},
        )
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id, populate_existing=True)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            return record

    async def _approval_conflict(
        self,
        outbox_id: str,
        *,
        action: str,
        reason: str,
        detail: str,
        actor: str,
        original: str,
        proposed: str,
    ) -> NoReturn:
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is not None and record.status == "pending_approval":
                record.last_error_code = ErrorCode.POLICY_BLOCKED
                record.last_error_message = detail[:500]
                await session.commit()
        await write_audit(
            self.database,
            action=action,
            target_type="outbox_message",
            target_id=outbox_id,
            details={
                "result": "blocked",
                "reason": reason,
                "original_chars": len(original),
                "new_chars": len(proposed),
                "original_sha256": content_digest(original),
                "new_sha256": content_digest(proposed),
            },
            actor=actor,
        )
        raise AppError(
            ErrorCode.CONFLICT,
            detail,
            status_code=409,
            details={"reason": reason},
        )

    async def _fail_output(self, outbox_id: str, reason: str | None, max_chars: int) -> OutboxMessage:
        """发送前审查失败：直接终态，绝不排期重试或发送。"""
        code = {
            REASON_SENSITIVE: ErrorCode.SENSITIVE_OUTPUT,
            REASON_EMPTY: ErrorCode.OUTPUT_EMPTY,
            REASON_TOO_LONG: ErrorCode.OUTPUT_TOO_LONG,
        }.get(reason or "", ErrorCode.POLICY_BLOCKED)
        message = {
            REASON_SENSITIVE: "发送前审查发现疑似密码、验证码、证件号或密钥，已阻止发送。",
            REASON_EMPTY: "发送前审查发现内容为空，已阻止发送。",
            REASON_TOO_LONG: f"内容超过当前群级字数上限（{max_chars}），已阻止发送。",
        }.get(reason or "", "发送前审查未通过，已阻止发送。")
        async with self.database.session() as session:
            record = await session.get(OutboxMessage, outbox_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
            record.status = "failed"
            record.next_attempt_at = None
            record.last_error_code = code
            record.last_error_message = message
            await session.commit()
            await session.refresh(record)
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
