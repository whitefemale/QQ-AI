"""消息持久化、去重与查询。数据库唯一约束是去重的最终保证。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.db.session import Database
from app.models.message import Message
from app.schemas.message import CanonicalMessage

logger = logging.getLogger(__name__)


class MessageService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def persist_incoming(
        self,
        message: CanonicalMessage,
        *,
        group_id: str | None,
        processing_status: str = "received",
    ) -> Message | None:
        """保存入站消息；重复事件返回 None（不重复处理、不重复回复）。"""
        record = Message(
            platform_message_id=message.message_id,
            account_id=message.account_id,
            group_id=group_id,
            conversation_id=message.conversation_id,
            conversation_type=message.conversation_type,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            is_self=message.is_self_message,
            direction="inbound",
            content_text=message.text,
            segments_json=[segment.model_dump(mode="json") for segment in message.segments],
            reply_to_message_id=message.reply_to_message_id,
            event_timestamp=message.timestamp,
            processing_status=processing_status,
        )
        async with self.database.session() as session:
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "重复消息事件已忽略",
                    extra={"account_id": message.account_id, "platform_message_id": message.message_id},
                )
                return None
            await session.refresh(record)
            return record

    async def mark(
        self,
        message_id: str,
        *,
        status: str,
        trigger_reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        model_latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        async with self.database.session() as session:
            record = await session.get(Message, message_id)
            if record is None:
                return
            record.processing_status = status
            if trigger_reason is not None:
                record.trigger_reason = trigger_reason
            record.error_code = error_code
            record.error_message = error_message
            if model_latency_ms is not None:
                record.model_latency_ms = model_latency_ms
            if input_tokens is not None:
                record.input_tokens = input_tokens
            if output_tokens is not None:
                record.output_tokens = output_tokens
            await session.commit()

    async def get(self, message_id: str) -> Message | None:
        async with self.database.session() as session:
            return await session.get(Message, message_id)

    async def find_by_platform_id(
        self,
        account_id: str,
        platform_message_id: str,
        *,
        direction: str = "inbound",
    ) -> Message | None:
        async with self.database.session() as session:
            return await session.scalar(
                select(Message).where(
                    Message.account_id == account_id,
                    Message.platform_message_id == platform_message_id,
                    Message.direction == direction,
                )
            )

    async def reply_targets_self(self, account_id: str, reply_to_message_id: str | None) -> bool:
        if not reply_to_message_id:
            return False
        record = await self.find_by_platform_id(account_id, reply_to_message_id, direction="outbound")
        return record is not None and record.is_self

    async def reply_target_text(self, account_id: str, reply_to_message_id: str | None) -> str | None:
        if not reply_to_message_id:
            return None
        record = await self.find_by_platform_id(account_id, reply_to_message_id, direction="inbound")
        if record is None:
            record = await self.find_by_platform_id(account_id, reply_to_message_id, direction="outbound")
        if record is None or not record.content_text:
            return None
        return record.content_text[:500]

    async def record_outbound(
        self,
        *,
        account_id: str,
        group_id: str | None,
        conversation_id: str,
        conversation_type: str,
        content: str,
        platform_message_id: str,
        sender_id: str,
        sender_name: str | None = "AI 群友",
        reply_to_message_id: str | None = None,
        event_timestamp: datetime | None = None,
    ) -> Message | None:
        record = Message(
            platform_message_id=platform_message_id,
            account_id=account_id,
            group_id=group_id,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            sender_id=sender_id,
            sender_name=sender_name,
            is_self=True,
            direction="outbound",
            content_text=content,
            segments_json=[{"type": "text", "text": content}],
            reply_to_message_id=reply_to_message_id,
            event_timestamp=event_timestamp or utcnow(),
            processing_status="sent",
            trigger_reason="reply",
        )
        async with self.database.session() as session:
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            await session.refresh(record)
            return record

    async def recent_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 20,
        before: datetime | None = None,
    ) -> list[Message]:
        async with self.database.session() as session:
            query = select(Message).where(Message.conversation_id == conversation_id)
            if before is not None:
                query = query.where(Message.event_timestamp <= before)
            query = query.order_by(Message.event_timestamp.desc()).limit(max(1, min(limit, 100)))
            records = list((await session.execute(query)).scalars())
        records.reverse()
        return records

    async def outbound_stats(self, group_id: str, since: datetime) -> dict[str, Any]:
        async with self.database.session() as session:
            records = list(
                (
                    await session.execute(
                        select(Message.event_timestamp)
                        .where(
                            Message.group_id == group_id,
                            Message.direction == "outbound",
                            Message.event_timestamp >= since,
                        )
                        .order_by(Message.event_timestamp.desc())
                    )
                ).scalars()
            )
        return {"count": len(records), "last_at": records[0] if records else None}
