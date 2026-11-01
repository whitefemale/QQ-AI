"""QQ 群与成员配置。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("account_id", "platform_group_id", name="uq_groups_account_platform"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_group_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_mode: Mapped[str] = mapped_column(String(32), default="observe", nullable=False)
    # 为空表示跟随全局 settings.max_reply_chars / context_message_limit。
    max_reply_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_message_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persona_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )
    llm_provider_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    llm_fallback_provider_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    allow_memory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_memory_extraction: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    memory_extraction_watermark_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    memory_extraction_watermark_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    memory_extraction_last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    memory_extraction_last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    allow_tools: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_proactive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    admin_user_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    quiet_hours_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    rate_limit_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    keywords_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    group_rules_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)


class Member(Base, TimestampMixin):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("account_id", "platform_user_id", name="uq_members_account_user"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    labels_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_from_memory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    muted_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
