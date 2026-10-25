"""消息、发送队列与处理结果。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("account_id", "platform_message_id", "direction", name="uq_messages_account_platform_dir"),
        Index("ix_messages_conversation_time", "conversation_id", "event_timestamp"),
        Index("ix_messages_group_time", "group_id", "event_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    platform_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    conversation_type: Mapped[str] = mapped_column(String(16), default="group", nullable=False)
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_self: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    segments_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), default="received", nullable=False, index=True)
    trigger_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OutboxMessage(Base, TimestampMixin):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    adapter_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    conversation_type: Mapped[str] = mapped_column(String(16), default="group", nullable=False)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_platform_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
